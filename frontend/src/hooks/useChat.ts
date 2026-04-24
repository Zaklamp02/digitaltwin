import { useCallback, useEffect, useRef, useState } from "react";

export type Role = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  /** Set to true while tokens are still arriving. */
  streaming?: boolean;
  /** Files that were retrieved for this response, for transparency. */
  chunksUsed?: { file: string; section: string; score: number; tier: string }[];
}

export interface UseChatOptions {
  /** token from URL `?t=...` */
  token: string;
  /** Called with each new complete sentence from the assistant as it streams. */
  onSentence?: (text: string, messageId: string) => void;
  /** Called when backend emits conversation_end. */
  onConversationEnd?: (message: string) => void;
}

export interface UseChatReturn {
  messages: ChatMessage[];
  send: (text: string) => Promise<void>;
  reset: () => void;
  loading: boolean;
  error: string | null;
  sessionId: string | null;
  conversationEnded: boolean;
  conversationEndMessage: string | null;
}

function newId(): string {
  // Browser-safe UUID
  return (crypto as any)?.randomUUID?.() ??
    Math.random().toString(36).slice(2) + Date.now().toString(36);
}

const SENTENCE_END = /([.!?])(?:\s|$)/;

export function useChat(opts: UseChatOptions): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [conversationEnded, setConversationEnded] = useState(false);
  const [conversationEndMessage, setConversationEndMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages([]);
    setError(null);
    setSessionId(null);
    setConversationEnded(false);
    setConversationEndMessage(null);
    setLoading(false);
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading || conversationEnded) return;
      setError(null);

      const userMsg: ChatMessage = { id: newId(), role: "user", content: trimmed };
      const assistantId = newId();
      const assistantMsg: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setLoading(true);

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      const history = [
        ...messages.filter((m) => !m.streaming).map((m) => ({ role: m.role, content: m.content })),
        { role: "user" as const, content: trimmed },
      ];

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          signal: ctrl.signal,
          headers: {
            "Content-Type": "application/json",
            "X-Access-Token": opts.token,
            ...(sessionId ? { "X-Session-Id": sessionId } : {}),
          },
          body: JSON.stringify({ messages: history }),
        });

        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          const reason = detail?.detail?.reason ?? `HTTP ${res.status}`;
          throw new Error(reason);
        }

        const nextSession = res.headers.get("X-Session-Id");
        if (nextSession) setSessionId(nextSession);
        if (!res.body) throw new Error("no response body");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let pendingSentence = "";

        // Push a partial token into the current assistant message + drip sentences.
        const pushToken = (tok: string) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + tok } : m)),
          );
          pendingSentence += tok;
          let match;
          while ((match = pendingSentence.match(SENTENCE_END))) {
            const end = (match.index ?? 0) + match[0].length;
            const sentence = pendingSentence.slice(0, end).trim();
            pendingSentence = pendingSentence.slice(end);
            if (sentence) opts.onSentence?.(sentence, assistantId);
          }
        };

        const applyEvent = (event: string, data: string) => {
          switch (event) {
            case "session": {
              try {
                const payload = JSON.parse(data);
                if (payload.session_id) setSessionId(payload.session_id);
              } catch { /* ignore */ }
              break;
            }
            case "chunks_used": {
              try {
                const chunks = JSON.parse(data);
                setMessages((prev) =>
                  prev.map((m) => (m.id === assistantId ? { ...m, chunksUsed: chunks } : m)),
                );
              } catch { /* ignore */ }
              break;
            }
            case "token":
              pushToken(data);
              break;
            case "conversation_end": {
              try {
                const payload = JSON.parse(data);
                setConversationEnded(true);
                setConversationEndMessage(payload.message ?? "This session is over.");
                opts.onConversationEnd?.(payload.message ?? "");
              } catch { /* ignore */ }
              break;
            }
            case "error": {
              try {
                const payload = JSON.parse(data);
                setError(payload.message ?? "stream error");
              } catch {
                setError("stream error");
              }
              break;
            }
            case "done":
              // flush trailing partial sentence as a final sentence if any
              if (pendingSentence.trim()) {
                opts.onSentence?.(pendingSentence.trim(), assistantId);
                pendingSentence = "";
              }
              break;
          }
        };

        // Parse text/event-stream frames (blank line separated).
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let idx;
          while ((idx = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const lines = frame.split(/\r?\n/);
            let event = "message";
            let dataLines: string[] = [];
            for (const line of lines) {
              if (line.startsWith("event:")) event = line.slice(6).trim();
              else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^\s/, ""));
            }
            applyEvent(event, dataLines.join("\n"));
          }
        }

        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, streaming: false } : m)),
        );
      } catch (err: any) {
        if (err?.name === "AbortError") return;
        setError(err?.message ?? "something went wrong");
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, streaming: false } : m)),
        );
      } finally {
        setLoading(false);
        abortRef.current = null;
      }
    },
    [messages, sessionId, loading, conversationEnded, opts],
  );

  useEffect(() => () => abortRef.current?.abort(), []);

  return {
    messages,
    send,
    reset,
    loading,
    error,
    sessionId,
    conversationEnded,
    conversationEndMessage,
  };
}
