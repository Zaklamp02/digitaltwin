import { useCallback, useEffect, useRef } from "react";

/**
 * Streaming TTS — PCM edition.
 *
 * /api/speak now returns raw PCM (24 kHz, 16-bit signed, little-endian, mono).
 * We stream the response body through Web Audio API AudioBufferSourceNodes,
 * scheduling each decoded chunk back-to-back so the first word plays as soon
 * as the first ~1 KB of data arrives — no full-blob buffering needed.
 */

const PCM_SAMPLE_RATE = 24000; // OpenAI PCM: 24 kHz

export function useTTS(token: string, enabled: boolean) {
  const queueRef = useRef<string[]>([]);
  const playingRef = useRef(false);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const scheduledEndRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const getCtx = () => {
    if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
      audioCtxRef.current = new AudioContext({ sampleRate: PCM_SAMPLE_RATE });
      scheduledEndRef.current = 0;
    }
    // Resume if browser suspended the context (autoplay policy)
    if (audioCtxRef.current.state === "suspended") {
      audioCtxRef.current.resume().catch(() => {});
    }
    return audioCtxRef.current;
  };

  /** Decode a PCM chunk (Int16, little-endian) and schedule it for playback. */
  const scheduleChunk = (ctx: AudioContext, int16: Uint8Array) => {
    const sampleCount = Math.floor(int16.length / 2);
    if (sampleCount === 0) return;
    const audioBuffer = ctx.createBuffer(1, sampleCount, PCM_SAMPLE_RATE);
    const channel = audioBuffer.getChannelData(0);
    const view = new DataView(int16.buffer, int16.byteOffset, sampleCount * 2);
    for (let i = 0; i < sampleCount; i++) {
      channel[i] = view.getInt16(i * 2, /* littleEndian */ true) / 32768;
    }
    const src = ctx.createBufferSource();
    src.buffer = audioBuffer;
    src.connect(ctx.destination);
    const startAt = Math.max(scheduledEndRef.current, ctx.currentTime);
    src.start(startAt);
    scheduledEndRef.current = startAt + audioBuffer.duration;
  };

  /** Stream one sentence from /api/speak into the Web Audio pipeline. */
  const streamSentence = async (text: string, ctrl: AbortController) => {
    const res = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Access-Token": token },
      body: JSON.stringify({ text }),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`speak HTTP ${res.status}`);
    if (!res.body) throw new Error("no response body");

    const ctx = getCtx();
    // If starting a fresh sentence after a gap, anchor to now
    if (scheduledEndRef.current < ctx.currentTime) {
      scheduledEndRef.current = ctx.currentTime;
    }

    const reader = res.body.getReader();
    let leftover = new Uint8Array(0);

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;

      // Prepend any leftover bytes from the previous chunk
      const combined = new Uint8Array(leftover.length + value.length);
      combined.set(leftover);
      combined.set(value, leftover.length);

      const usableBytes = Math.floor(combined.length / 2) * 2; // must be even (16-bit samples)
      leftover = combined.slice(usableBytes);
      scheduleChunk(ctx, combined.slice(0, usableBytes));
    }
    // Leftover (< 2 bytes) is discarded — too short to be a sample
  };

  const runQueue = useCallback(async () => {
    if (playingRef.current) return;
    playingRef.current = true;
    try {
      while (queueRef.current.length > 0) {
        const text = queueRef.current.shift()!;
        const ctrl = new AbortController();
        abortRef.current = ctrl;
        try {
          await streamSentence(text, ctrl);
          // Wait for the scheduled audio to finish before processing the next sentence
          const ctx = audioCtxRef.current;
          if (ctx) {
            const remaining = scheduledEndRef.current - ctx.currentTime;
            if (remaining > 0) {
              await new Promise<void>((r) => setTimeout(r, remaining * 1000 + 50));
            }
          }
        } catch (err: any) {
          if (err?.name === "AbortError") break; // stop() was called
          console.warn("[useTTS] sentence error:", err);
        }
      }
    } finally {
      playingRef.current = false;
      abortRef.current = null;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const enqueue = useCallback(
    (text: string) => {
      if (!enabled) return;
      const clean = text.trim();
      if (!clean) return;
      queueRef.current.push(clean);
      void runQueue();
    },
    [enabled, runQueue],
  );

  const stop = useCallback(() => {
    queueRef.current = [];
    abortRef.current?.abort();
    abortRef.current = null;
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
      scheduledEndRef.current = 0;
    }
    playingRef.current = false;
  }, []);

  const replay = useCallback(
    (text: string) => {
      if (!enabled) return;
      stop();
      queueRef.current.push(text.trim());
      void runQueue();
    },
    [enabled, stop, runQueue],
  );

  useEffect(() => () => stop(), [stop]);

  return { enqueue, replay, stop };
}
