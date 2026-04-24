import { useCallback, useEffect, useRef, useState } from "react";

export interface UseSTT {
  recording: boolean;
  transcribing: boolean;
  error: string | null;
  /**
   * Start recording — returns a Promise that resolves with the transcript
   * once VAD detects end-of-speech (or the user clicks the mic again to stop
   * manually). Calling toggle() while already recording stops it immediately.
   */
  toggle: () => Promise<string | null>;
}

// VAD tuning constants
const SPEECH_THRESHOLD_RMS = 0.015;  // energy above this = speech detected
const SILENCE_THRESHOLD_RMS = 0.01;  // energy below this = silence
const SILENCE_DURATION_MS = 1500;    // auto-stop after this many ms of silence
const VAD_INTERVAL_MS = 80;          // analyse every 80 ms

export function useSTT(token: string): UseSTT {
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const resolveRef = useRef<((t: string | null) => void) | null>(null);

  // VAD refs
  const vadTimerRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const vadSilenceMsRef = useRef(0);
  const speechDetectedRef = useRef(false);

  const stopVad = useCallback(() => {
    if (vadTimerRef.current !== null) {
      clearInterval(vadTimerRef.current);
      vadTimerRef.current = null;
    }
    analyserRef.current?.disconnect();
    analyserRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    vadSilenceMsRef.current = 0;
    speechDetectedRef.current = false;
  }, []);

  const startVad = useCallback(
    (stream: MediaStream, onSilenceStop: () => void) => {
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      analyserRef.current = analyser;
      ctx.createMediaStreamSource(stream).connect(analyser);

      const buf = new Float32Array(analyser.fftSize);

      vadTimerRef.current = window.setInterval(() => {
        if (!analyserRef.current) return;
        analyserRef.current.getFloatTimeDomainData(buf);
        const rms = Math.sqrt(buf.reduce((s, v) => s + v * v, 0) / buf.length);

        if (!speechDetectedRef.current) {
          if (rms > SPEECH_THRESHOLD_RMS) speechDetectedRef.current = true;
        } else {
          if (rms < SILENCE_THRESHOLD_RMS) {
            vadSilenceMsRef.current += VAD_INTERVAL_MS;
            if (vadSilenceMsRef.current >= SILENCE_DURATION_MS) {
              stopVad();
              onSilenceStop();
            }
          } else {
            vadSilenceMsRef.current = 0;
          }
        }
      }, VAD_INTERVAL_MS);
    },
    [stopVad],
  );

  const toggle = useCallback(async () => {
    if (recording && recorderRef.current) {
      // Manual stop — the existing resolveRef promise resolves via onstop handler
      stopVad();
      if (recorderRef.current.state === "recording") recorderRef.current.stop();
      return null;
    }

    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunksRef.current = [];

      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        stopVad();
        setRecording(false);
        setTranscribing(true);
        try {
          const blob = new Blob(chunksRef.current, { type: mime || "audio/webm" });
          const fd = new FormData();
          fd.append("file", blob, "speech.webm");
          const res = await fetch("/api/transcribe", {
            method: "POST",
            headers: { "X-Access-Token": token },
            body: fd,
          });
          if (!res.ok) throw new Error(`transcribe HTTP ${res.status}`);
          const data = await res.json();
          resolveRef.current?.(data.text ?? "");
        } catch (err: any) {
          setError(err?.message ?? "transcription failed");
          resolveRef.current?.(null);
        } finally {
          setTranscribing(false);
          resolveRef.current = null;
        }
      };

      recorderRef.current = rec;
      rec.start();
      setRecording(true);

      startVad(stream, () => {
        if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      });

      // Return a promise that resolves when onstop + transcription finish
      return new Promise<string | null>((resolve) => {
        resolveRef.current = resolve;
      });
    } catch (err: any) {
      setError(err?.message ?? "mic permission denied");
      return null;
    }
  }, [recording, token, stopVad, startVad]);

  // Cleanup on unmount
  useEffect(() => () => stopVad(), [stopVad]);

  return { recording, transcribing, error, toggle };
}
