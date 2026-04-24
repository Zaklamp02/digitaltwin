import { useEffect, useRef, useState } from "react";

export const VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"] as const;
export type Voice = (typeof VOICES)[number];

interface Props {
  ttsEnabled: boolean;
  setTtsEnabled: (v: boolean) => void;
  voice: Voice;
  setVoice: (v: Voice) => void;
  onClear: () => void;
  onAdmin: () => void;
  version: string;
}

export function SettingsMenu(props: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="h-9 w-9 rounded-full border border-ink/10 bg-white flex items-center justify-center text-ink/60 hover:text-accent"
        aria-label="Settings"
        title="Settings"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 top-11 z-20 w-64 rounded-xl border border-ink/10 bg-white shadow-lg p-3 text-sm">
          <label className="flex items-center justify-between gap-2 py-1.5">
            <span>Speak replies</span>
            <input
              type="checkbox"
              checked={props.ttsEnabled}
              onChange={(e) => props.setTtsEnabled(e.target.checked)}
              className="accent-[theme(colors.accent.DEFAULT)] h-4 w-4"
            />
          </label>
          <label className="flex items-center justify-between gap-2 py-1.5">
            <span>Voice</span>
            <select
              value={props.voice}
              onChange={(e) => props.setVoice(e.target.value as Voice)}
              className="rounded border border-ink/15 bg-white px-2 py-1 text-sm"
            >
              {VOICES.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <div className="h-px bg-ink/10 my-2" />
          <button
            onClick={() => {
              props.onClear();
              setOpen(false);
            }}
            className="w-full text-left rounded-md px-2 py-1.5 hover:bg-ink/5 text-ink/80"
          >
            Clear conversation
          </button>
          <button
            onClick={() => {
              props.onAdmin();
              setOpen(false);
            }}
            className="w-full text-left rounded-md px-2 py-1.5 hover:bg-ink/5 text-ink/60 text-xs"
          >
            Admin dashboard ↗
          </button>
          <div className="mt-2 text-[11px] text-ink/40 px-1">v{props.version}</div>
        </div>
      )}
    </div>
  );
}
