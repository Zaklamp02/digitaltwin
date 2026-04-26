import { useEffect, useRef, useState } from "react";

interface Props {
  disabled: boolean;
  loading: boolean;
  recording: boolean;
  transcribing: boolean;
  onSend: (text: string) => void;
  onMic: () => void;
  /** External text (e.g. just-transcribed speech) to inject into the field. */
  injected?: string;
}

export function InputBar({
  disabled,
  loading,
  recording,
  transcribing,
  onSend,
  onMic,
  injected,
}: Props) {
  const [value, setValue] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (injected !== undefined && injected.length > 0) {
      setValue((prev) => (prev ? prev + " " + injected : injected));
      // focus + move caret to end
      requestAnimationFrame(() => {
        taRef.current?.focus();
        const len = taRef.current?.value.length ?? 0;
        taRef.current?.setSelectionRange(len, len);
      });
    }
  }, [injected]);

  const submit = () => {
    const t = value.trim();
    if (!t || disabled || loading) return;
    onSend(t);
    setValue("");
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const micLabel = transcribing
    ? "Transcribing…"
    : recording
      ? "Stop recording"
      : "Speak your question";

  return (
    <div className="border-t border-ink/10 dark:border-white/10 bg-white dark:bg-gray-900 px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <div className="flex items-end gap-2">
        <button
          type="button"
          onClick={onMic}
          disabled={disabled || loading}
          aria-label={micLabel}
          className={[
            "shrink-0 h-11 w-11 rounded-full border flex items-center justify-center transition",
            recording
              ? "bg-red-500 border-red-500 text-white animate-pulse"
              : transcribing
                ? "bg-ink/5 dark:bg-white/5 border-ink/20 dark:border-white/20 text-ink/40 dark:text-white/40"
                : "bg-white dark:bg-gray-800 border-ink/15 dark:border-white/15 text-ink dark:text-white hover:border-accent hover:text-accent",
          ].join(" ")}
          title={micLabel}
        >
          {/* mic glyph */}
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
        </button>
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKey}
          rows={1}
          placeholder={disabled ? "Conversation ended." : "Ask about Sebastiaan…"}
          disabled={disabled}
          className="flex-1 resize-none rounded-2xl border border-ink/15 dark:border-white/15 bg-white dark:bg-gray-800 px-4 py-2.5 text-[15px] text-ink dark:text-white leading-6 placeholder:text-ink/40 dark:placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:bg-ink/5 dark:disabled:bg-white/5 disabled:text-ink/40 dark:disabled:text-white/40"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || loading || !value.trim()}
          aria-label="Send"
          className="shrink-0 h-11 w-11 rounded-full border bg-white dark:bg-gray-800 border-ink/15 dark:border-white/15 text-ink dark:text-white flex items-center justify-center hover:border-accent hover:text-accent disabled:opacity-30 transition"
        >
          {/* send / paper-plane glyph */}
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  );
}
