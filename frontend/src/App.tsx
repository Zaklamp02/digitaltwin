import { useEffect, useMemo, useState } from "react";
import { Admin } from "./components/Admin";
import { ChatStream } from "./components/ChatStream";
import { ConversationEnd } from "./components/ConversationEnd";
import { InputBar } from "./components/InputBar";
import { useChat } from "./hooks/useChat";
import { useSTT } from "./hooks/useSTT";
import { useTTS } from "./hooks/useTTS";

function readTokenFromUrl(): string {
  if (typeof window === "undefined") return "";
  const params = new URLSearchParams(window.location.search);
  return params.get("t") ?? "";
}

function readPageFromUrl(): string {
  if (typeof window === "undefined") return "";
  const params = new URLSearchParams(window.location.search);
  return params.get("page") ?? "";
}

export default function App() {
  const [token] = useState<string>(() => readTokenFromUrl());
  const [page, setPage] = useState<string>(() => readPageFromUrl());

  if (page === "admin") {
    return (
      <Admin
        token={token}
        onExit={() => {
          setPage("");
          window.history.replaceState({}, "", window.location.pathname + (token ? `?t=${token}` : ""));
        }}
      />
    );
  }

  return (
    <ChatApp
      token={token}
      onAdmin={() => {
        setPage("admin");
        window.history.replaceState({}, "", `?page=admin${token ? `&t=${token}` : ""}`);
      }}
    />
  );
}

function ChatApp({ token, onAdmin: _onAdmin }: { token: string; onAdmin: () => void }) {
  // "voice" = last input came from mic → auto-speak replies
  // "text"  = last input typed      → silent replies
  const [inputMode, setInputMode] = useState<"voice" | "text">("text");
  const [injectedInput, setInjectedInput] = useState<string>("");
  const [showBio, setShowBio] = useState(false);

  // Dark mode — persisted in localStorage, synced to <html> class
  const [dark, setDark] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    const saved = localStorage.getItem("darkMode");
    if (saved !== null) return saved === "true";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("darkMode", String(dark));
  }, [dark]);

  const ttsEnabled = inputMode === "voice";
  const tts = useTTS(token, ttsEnabled);

  const chat = useChat({
    token,
    onSentence: (sentence) => tts.enqueue(sentence),
    onConversationEnd: () => {},
  });

  const stt = useSTT(token);

  const handleMic = async () => {
    const transcript = await stt.toggle();
    if (transcript) {
      setInputMode("voice");   // STT input → auto-speak the reply
      setInjectedInput(transcript);
    }
  };

  const headerStatus = useMemo(() => {
    if (chat.error) return <span className="text-red-500">Error: {chat.error}</span>;
    if (chat.loading) return <span className="text-ink/40">Thinking…</span>;
    if (stt.transcribing) return <span className="text-ink/40">Transcribing…</span>;
    if (stt.recording) return <span className="text-red-500">● recording</span>;
    return null;
  }, [chat.error, chat.loading, stt.transcribing, stt.recording]);

  const newConversation = () => {
    tts.stop();
    chat.reset();
    setInputMode("text");
  };

  return (
    <div className="mx-auto flex h-[100dvh] w-full max-w-[720px] flex-col bg-paper dark:bg-gray-950">
      <header className="flex items-center gap-3 px-4 py-3 border-b border-ink/10 dark:border-white/10 bg-white dark:bg-gray-900">
        <button
          className="h-10 w-10 rounded-full bg-ink/10 overflow-hidden shrink-0 cursor-pointer ring-0 hover:ring-2 hover:ring-accent/40 transition-all focus:outline-none"
          onClick={() => setShowBio(true)}
          aria-label="View profile"
          title="View profile"
        >
          <img
            src="/avatar_digitaltwin.png"
            alt="Digital Twin"
            className="h-full w-full object-cover"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
            }}
          />
        </button>
        <div className="flex-1 min-w-0">
          <div className="font-semibold leading-tight dark:text-white">Sebastiaan's Digital Twin</div>
          <div className="text-[11px] text-ink/50 dark:text-white/40 leading-tight h-4">{headerStatus}</div>
        </div>
        {/* Dark mode toggle */}
        <button
          onClick={() => setDark((d) => !d)}
          className="h-9 w-9 rounded-full border border-ink/10 dark:border-white/10 bg-white dark:bg-white/5 flex items-center justify-center text-ink/60 dark:text-white/60 hover:text-accent dark:hover:text-accent transition-colors"
          aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
          title={dark ? "Light mode" : "Dark mode"}
        >
          {dark ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
              <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
          )}
        </button>
      </header>

      <ChatStream
        messages={chat.messages}
        ttsEnabled={ttsEnabled}
        onReplay={(text) => tts.replay(text)}
        onSend={(text) => { void chat.send(text); }}
        token={token}
      />

      {chat.conversationEnded ? (
        <ConversationEnd message={chat.conversationEndMessage} onNew={newConversation} />
      ) : (
        <InputBar
          disabled={chat.conversationEnded}
          loading={chat.loading}
          recording={stt.recording}
          transcribing={stt.transcribing}
          injected={injectedInput}
          onSend={(t) => {
            setInputMode("text");  // keyboard send → text mode, no auto-speech
            setInjectedInput("");
            void chat.send(t);
          }}
          onMic={handleMic}
        />
      )}

      {showBio && <BioModal onClose={() => setShowBio(false)} onAdmin={_onAdmin} />}
    </div>
  );
}


// ── Bio modal ─────────────────────────────────────────────────────────────────

function BioModal({ onClose, onAdmin }: { onClose: () => void; onAdmin: () => void }) {
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header bar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">About</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 bg-gray-100 rounded-full w-7 h-7 flex items-center justify-center text-sm"
            aria-label="Close"
          >✕</button>
        </div>

        {/* Two cards side by side */}
        <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-gray-100">

          {/* Left: the real person */}
          <div className="flex flex-col items-center px-6 py-6 gap-4">
            <img
              src="/avatar_sebastiaan.png"
              alt="Sebastiaan den Boer"
              className="w-24 h-24 rounded-full object-cover shadow border-2 border-white ring-2 ring-indigo-100"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
            />
            <div className="text-center">
              <h3 className="font-bold text-gray-900 text-lg leading-tight">Sebastiaan den Boer</h3>
              <p className="text-xs text-gray-500 mt-0.5">MSc Cognitive Neuroscience · Executive MBA</p>
              <p className="text-sm font-medium text-gray-700 mt-2">Director of Data Science & AI</p>
              <p className="text-sm text-gray-500">Youwe · Utrecht, NL</p>
            </div>
            <p className="text-sm text-gray-600 text-center leading-relaxed">
              Sebastiaan builds AI systems that make high-stakes decisions better.
              From forensic investigations at the Dutch tax authority to multi-agent pricing
              systems delivering €80M/year in margin — he operates at both executive altitude
              and hands-on engineering.
            </p>
            <div className="flex flex-col items-center gap-1.5 text-sm">
              <a href="mailto:sebastiaandenboer@gmail.com" className="text-indigo-600 hover:underline">
                sebastiaandenboer@gmail.com
              </a>
              <a href="https://linkedin.com/in/svdenboer" target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline">
                linkedin.com/in/svdenboer
              </a>
              <a
                href="/api/cv"
                download="Sebastiaan_den_Boer_CV.pdf"
                className="mt-1 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-white text-xs font-medium hover:bg-indigo-700 transition-colors"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                Download CV
              </a>
            </div>
          </div>

          {/* Right: the digital twin */}
          <div className="flex flex-col items-center px-6 py-6 gap-4">
            <img
              src="/avatar_digitaltwin.png"
              alt="Digital Twin"
              className="w-24 h-24 rounded-full object-cover shadow border-2 border-white ring-2 ring-emerald-100"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
            />
            <div className="text-center">
              <h3 className="font-bold text-gray-900 text-lg leading-tight">Sebastiaan's Digital Twin</h3>
              <p className="text-xs text-gray-500 mt-0.5">AI agent · Always on</p>
              <p className="text-sm font-medium text-gray-700 mt-2">Ask me anything about him</p>
              <p className="text-sm text-gray-500">Career · Projects · Views</p>
            </div>
            <div className="text-sm text-gray-600 text-center leading-relaxed space-y-2">
              <p>
                This is an AI agent trained on Sebastiaan's career history, projects, opinions,
                and personality — built so you can get real answers without scheduling a call.
              </p>
              <p>
                It speaks in first person and draws on a private knowledge graph.
                Recruiter-tier and personal-tier tokens unlock more depth.
              </p>
            </div>
            <div className="mt-auto pt-2 text-xs text-gray-400 text-center space-y-0.5">
              <p>Powered by OpenAI + ChromaDB</p>
              <p>Knowledge: career · projects · stack · opinions · FAQ</p>
              <button
                onClick={() => { onClose(); onAdmin(); }}
                className="mt-2 text-gray-300 hover:text-gray-400 transition-colors"
              >
                Admin ↗
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
