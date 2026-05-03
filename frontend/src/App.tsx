import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Admin } from "./components/Admin";
import { ChatStream } from "./components/ChatStream";
import { ConversationEnd } from "./components/ConversationEnd";
import { InputBar } from "./components/InputBar";
import { MindscapeCanvas, GraphNode, GraphEdge, PILLAR_COLORS } from "./components/MindscapeCanvas";
import { useChat } from "./hooks/useChat";
import { useSTT } from "./hooks/useSTT";
import { useTTS } from "./hooks/useTTS";
import { useTranslation } from "./hooks/useTranslation";

/* ══════════════════════════════════════════════════════════════════════
   Routing helpers
   ══════════════════════════════════════════════════════════════════════ */

function readTokenFromUrl(): string {
  if (typeof window === "undefined") return "";
  const params = new URLSearchParams(window.location.search);
  return params.get("t") ?? "";
}

function readPageFromUrl(): string {
  if (typeof window === "undefined") return "";
  if (window.location.pathname === "/chat") return "chat";
  const params = new URLSearchParams(window.location.search);
  return params.get("page") ?? "";
}

/* ══════════════════════════════════════════════════════════════════════
   App (root)
   ══════════════════════════════════════════════════════════════════════ */

export default function App() {
  const [token] = useState<string>(() => readTokenFromUrl());
  const [page, setPage] = useState<string>(() => readPageFromUrl());

  // Dark mode
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

  // Language
  const [language, setLanguage] = useState<"nl" | "en" | null>(() => {
    if (typeof window === "undefined") return null;
    // URL param takes priority (for shareable links like ?lang=nl)
    const params = new URLSearchParams(window.location.search);
    const urlLang = params.get("lang");
    if (urlLang === "nl" || urlLang === "en") return urlLang;
    const saved = localStorage.getItem("chatLanguage");
    return saved === "nl" || saved === "en" ? saved : null;
  });
  useEffect(() => {
    if (language) localStorage.setItem("chatLanguage", language);
    else localStorage.removeItem("chatLanguage");
  }, [language]);

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

  if (page === "chat") {
    return (
      <FullChat
        token={token}
        dark={dark}
        setDark={setDark}
        language={language}
        setLanguage={setLanguage}
        onBack={() => {
          setPage("");
          window.history.pushState({}, "", "/" + (token ? `?t=${token}` : ""));
        }}
        onAdmin={() => {
          setPage("admin");
          window.history.pushState({}, "", `?page=admin${token ? `&t=${token}` : ""}`);
        }}
      />
    );
  }

  return (
    <Mindscape
      token={token}
      dark={dark}
      setDark={setDark}
      language={language}
      setLanguage={setLanguage}
      onAdmin={() => {
        setPage("admin");
        window.history.pushState({}, "", `?page=admin${token ? `&t=${token}` : ""}`);
      }}
    />
  );
}

/* ══════════════════════════════════════════════════════════════════════
   Mindscape — the main landing experience
   ══════════════════════════════════════════════════════════════════════ */

const TWIN_NAME = "Basbot";

/* ── Tuning Panel (shown when ?tune=1 in URL) ── */
function TuningPanel() {
  const [, forceUpdate] = useState(0);
  const tune = (window as any).__graphTuning;
  if (!tune) return null;

  const sliders: { key: string; label: string; min: number; max: number; step: number }[] = [
    { key: "posScale",      label: "Node spread",    min: 0.3, max: 2.5, step: 0.05 },
    { key: "nodeScale",     label: "Node size",      min: 0.3, max: 3.0, step: 0.1 },
    { key: "fontSize",      label: "Label size",     min: 6,   max: 20,  step: 0.5 },
    { key: "childFontSize", label: "Child label",    min: 5,   max: 18,  step: 0.5 },
    { key: "childSpread",   label: "Child spread",   min: 0.5, max: 5.0, step: 0.1 },
    { key: "childRadius",   label: "Child radius",   min: 4,   max: 25,  step: 1 },
    { key: "edgeWidth",     label: "Edge width",     min: 0.2, max: 4.0, step: 0.1 },
    { key: "labelOffset",   label: "Label offset",   min: 5,   max: 30,  step: 1 },
  ];

  return (
    <div
      className="fixed bottom-16 right-2 z-[100] bg-white/95 dark:bg-gray-900/95 backdrop-blur-md rounded-xl shadow-2xl border border-ink/10 dark:border-white/10 p-3 text-xs w-[210px] max-h-[60vh] overflow-y-auto"
      style={{ scrollbarWidth: "thin" }}
      onTouchStart={(e) => e.stopPropagation()}
      onTouchMove={(e) => e.stopPropagation()}
    >
      <div className="font-bold text-ink dark:text-white mb-2">Graph Tuning</div>
      {sliders.map(({ key, label, min, max, step }) => (
        <div key={key} className="mb-2">
          <div className="flex justify-between text-ink/60 dark:text-white/60">
            <span>{label}</span>
            <span className="font-mono">{tune[key].toFixed(1)}</span>
          </div>
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={tune[key]}
            onChange={(e) => {
              tune[key] = parseFloat(e.target.value);
              forceUpdate((n) => n + 1);
            }}
            className="w-full h-1.5 accent-teal-500"
          />
        </div>
      ))}
      <button
        className="w-full mt-1 py-1.5 rounded-lg bg-accent/10 text-accent font-semibold hover:bg-accent/20 transition-colors"
        onClick={() => {
          const vals = sliders.map(({ key }) => `${key}: ${tune[key]}`).join("\n");
          navigator.clipboard?.writeText(vals);
          alert("Copied to clipboard:\n\n" + vals);
        }}
      >
        Copy values
      </button>
    </div>
  );
}

function Mindscape({
  token,
  dark,
  setDark,
  language,
  setLanguage,
  onAdmin: _onAdmin,
}: {
  token: string;
  dark: boolean;
  setDark: (v: boolean) => void;
  language: "nl" | "en" | null;
  setLanguage: (v: "nl" | "en" | null) => void;
  onAdmin: () => void;
}) {
  /* ── Translations ── */
  const { t, tn } = useTranslation(language, token);

  /* ── Graph data ── */
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);

  useEffect(() => {
    const headers: Record<string, string> = {};
    if (token) headers["X-Access-Token"] = token;
    fetch("/api/graph", { headers })
      .then((r) => r.json())
      .then((data: { nodes: GraphNode[]; edges: GraphEdge[] }) => {
        setGraphNodes(data.nodes);
        setGraphEdges(data.edges);
      })
      .catch(() => {});
  }, [token]);

  // Translate graph node titles when language or data changes
  const translatedNodes = useMemo(() =>
    graphNodes.map((n) => ({ ...n, title: tn(n.id, n.title) })),
    [graphNodes, tn],
  );

  /* ── Focus state ── */
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [focusedNodeTitle, setFocusedNodeTitle] = useState<string | null>(null);
  const [focusedPillarId, setFocusedPillarId] = useState<string | null>(null);
  const [heroVisible, setHeroVisible] = useState(true);
  const [chatActive, setChatActive] = useState(false);

  /* ── Chat ── */
  const chat = useChat({ token, language, onConversationEnd: () => {} });
  const stt = useSTT(token);
  const [inlineMessages, setInlineMessages] = useState<
    { id: string; role: "user" | "twin"; content: string }[]
  >([]);

  const addTwinMessage = useCallback((text: string) => {
    setInlineMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID?.() ?? String(Date.now()), role: "twin", content: text },
    ]);
  }, []);

  const addUserMessage = useCallback((text: string) => {
    setInlineMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID?.() ?? String(Date.now()), role: "user", content: text },
    ]);
  }, []);

  const handleNodeFocus = useCallback(
    (node: { id: string; title: string; pillarId?: string } | null) => {
      if (node) {
        setFocusedNodeId(node.id);
        setFocusedNodeTitle(node.title);
        setFocusedPillarId(node.pillarId ?? node.id);
        setHeroVisible(false);
        setChatActive(true);
      } else {
        setFocusedNodeId(null);
        setFocusedNodeTitle(null);
        setFocusedPillarId(null);
        if (inlineMessages.length === 0) {
          setHeroVisible(true);
          setChatActive(false);
        }
      }
    },
    [inlineMessages.length],
  );

  const goHome = useCallback(() => {
    setFocusedNodeId(null);
    setFocusedNodeTitle(null);
    setFocusedPillarId(null);
    setInlineMessages([]);
    setHeroVisible(true);
    setChatActive(false);
    chat.reset();
  }, [chat]);

  /* ── Settings dropdown ── */
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!settingsOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!settingsRef.current?.contains(e.target as Node)) setSettingsOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [settingsOpen]);

  /* ── Send inline message ── */
  const handleSend = useCallback(
    (text: string) => {
      if (!text.trim()) return;
      if (!chatActive) {
        setHeroVisible(false);
        setChatActive(true);
      }
      addUserMessage(text);
      void chat.send(text);
    },
    [chatActive, addUserMessage, chat],
  );

  const handleMic = useCallback(async () => {
    const transcript = await stt.toggle();
    if (transcript) handleSend(transcript);
  }, [stt, handleSend]);

  // Mirror streamed assistant messages into inline view
  useEffect(() => {
    const lastMsg = chat.messages[chat.messages.length - 1];
    if (!lastMsg || lastMsg.role !== "assistant") return;

    setInlineMessages((prev) => {
      const existing = prev.findIndex((m) => m.id === lastMsg.id);
      if (existing >= 0) {
        const updated = [...prev];
        updated[existing] = { ...updated[existing], content: lastMsg.content };
        return updated;
      }
      return [...prev, { id: lastMsg.id, role: "twin", content: lastMsg.content }];
    });
  }, [chat.messages]);

  // Show chat errors as inline messages
  useEffect(() => {
    if (chat.error) {
      const errText = chat.error === "conversation_limit"
        ? "I've reached the conversation limit for this session. Refresh to start a new one!"
        : `Something went wrong: ${chat.error}`;
      addTwinMessage(errText);
    }
  }, [chat.error, addTwinMessage]);

  /* ── Scroll area ref (canvas + messages) — auto-scroll to bottom ── */
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const [scrolledToChat, setScrolledToChat] = useState(false);

  useEffect(() => {
    if (scrollAreaRef.current) {
      scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight;
    }
  }, [inlineMessages]);

  useEffect(() => {
    const el = scrollAreaRef.current;
    if (!el) return;
    const onScroll = () => setScrolledToChat(el.scrollTop > 60);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Tuning mode
  const showTuning = useMemo(() => {
    if (typeof window === "undefined") return false;
    return new URLSearchParams(window.location.search).get("tune") === "1";
  }, []);

  return (
    <div className="h-[100dvh] bg-paper dark:bg-gray-950 transition-colors duration-500 snap-y snap-proximity overflow-y-auto">
      {showTuning && <TuningPanel />}
      {/* ════════════════════════════════════════════════════════════
          HERO SECTION (full viewport, stacked layout)
          ════════════════════════════════════════════════════════════ */}
      <div className="relative h-[100dvh] flex flex-col snap-start">

        {/* ── Settings button (floating over hero when hero visible) ── */}
        {heroVisible && (
        <div ref={settingsRef} className="absolute top-4 right-4 z-[10]">
          <button
            onClick={() => setSettingsOpen((v) => !v)}
            className="w-9 h-9 rounded-full border border-ink/10 dark:border-white/10 bg-white/80 dark:bg-gray-950/80 backdrop-blur-xl shadow-sm flex items-center justify-center hover:border-accent transition-all"
            title="Settings"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-ink/50 dark:text-white/50">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>

          {settingsOpen && (
            <div className="absolute top-11 right-0 w-56 rounded-xl border border-ink/[0.06] dark:border-white/10 bg-white dark:bg-gray-900 shadow-xl p-3 text-sm">
              {/* Dark/Light toggle */}
              <button
                onClick={() => setDark(!dark)}
                className="w-full flex items-center justify-between px-2 py-2 rounded-lg hover:bg-ink/5 dark:hover:bg-white/5 transition-colors text-ink dark:text-white"
              >
                <span>{dark ? t("ui.light_mode") : t("ui.dark_mode")}</span>
                {dark ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                    <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                  </svg>
                )}
              </button>

              {/* Language toggle */}
              <button
                onClick={() => setLanguage(language === "nl" ? "en" : "nl")}
                className="w-full flex items-center justify-between px-2 py-2 rounded-lg hover:bg-ink/5 dark:hover:bg-white/5 transition-colors text-ink dark:text-white"
              >
                <span>{language === "nl" ? t("ui.switch_to_english") : t("ui.switch_to_dutch")}</span>
                <span className="text-xs font-semibold text-ink/40 dark:text-white/40">{language === "nl" ? "NL" : "EN"}</span>
              </button>

              <div className="h-px bg-ink/[0.06] dark:bg-white/10 my-1.5" />
            </div>
          )}
        </div>
        )}

        {/* ── Compact Header (slides in when hero leaves) ── */}
        <div
          className={`shrink-0 z-[3] flex items-center justify-between px-4
            bg-white/75 dark:bg-gray-950/75 backdrop-blur-xl border-b border-ink/[0.06] dark:border-white/[0.06]
            transition-all duration-600 ease-out
            ${heroVisible ? "max-h-0 opacity-0 pointer-events-none overflow-hidden" : "max-h-[60px] opacity-100 py-2.5"}`}
        >
          <div className="flex items-center gap-2.5">
            <img
              src="/avatar_sebastiaan.png"
              alt="Sebastiaan den Boer"
              className="w-7 h-7 rounded-full object-cover border border-ink/[0.06] dark:border-white/10"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
            />
            <span
              onClick={goHome}
              className="font-semibold text-[0.82rem] tracking-tight text-ink dark:text-white cursor-pointer hover:text-accent dark:hover:text-accent transition-colors"
            >
              Sebastiaan den Boer
            </span>
          </div>
          <div className="flex items-center gap-4 text-[0.7rem]">
            <a href="#blog-section" className="text-ink/30 dark:text-white/30 hover:text-accent dark:hover:text-accent transition-colors no-underline">{t("ui.blog")}</a>
            <a href="#projects-section" className="text-ink/30 dark:text-white/30 hover:text-accent dark:hover:text-accent transition-colors no-underline">{t("ui.projects")}</a>
            <a href="#about-section" className="text-ink/30 dark:text-white/30 hover:text-accent dark:hover:text-accent transition-colors no-underline">{t("ui.about")}</a>
            <a href="https://linkedin.com/in/svdenboer" target="_blank" rel="noopener noreferrer" className="text-ink/30 dark:text-white/30 hover:text-accent dark:hover:text-accent transition-colors no-underline">{t("ui.linkedin")}</a>
            {/* Settings inside navbar */}
            <div ref={!heroVisible ? settingsRef : undefined} className="relative">
              <button
                onClick={() => setSettingsOpen((v) => !v)}
                className="w-7 h-7 rounded-full border border-ink/10 dark:border-white/10 bg-white/60 dark:bg-gray-950/60 flex items-center justify-center hover:border-accent transition-all"
                title="Settings"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-ink/50 dark:text-white/50">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
              </button>
              {settingsOpen && !heroVisible && (
                <div className="absolute top-9 right-0 w-56 rounded-xl border border-ink/[0.06] dark:border-white/10 bg-white dark:bg-gray-900 shadow-xl p-3 text-sm z-50">
                  <button
                    onClick={() => setDark(!dark)}
                    className="w-full flex items-center justify-between px-2 py-2 rounded-lg hover:bg-ink/5 dark:hover:bg-white/5 transition-colors text-ink dark:text-white"
                  >
                    <span>{dark ? t("ui.light_mode") : t("ui.dark_mode")}</span>
                    {dark ? (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
                        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                        <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
                        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                      </svg>
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                      </svg>
                    )}
                  </button>
                  <button
                    onClick={() => setLanguage(language === "nl" ? "en" : "nl")}
                    className="w-full flex items-center justify-between px-2 py-2 rounded-lg hover:bg-ink/5 dark:hover:bg-white/5 transition-colors text-ink dark:text-white"
                  >
                    <span>{language === "nl" ? t("ui.switch_to_english") : t("ui.switch_to_dutch")}</span>
                    <span className="text-xs font-semibold text-ink/40 dark:text-white/40">{language === "nl" ? "NL" : "EN"}</span>
                  </button>
                  <div className="h-px bg-ink/[0.06] dark:bg-white/10 my-1.5" />
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Scrollable area: canvas + chat messages ── */}
        <div
          ref={scrollAreaRef}
          className="flex-1 min-h-0 overflow-y-auto flex flex-col"
          style={{ scrollbarWidth: "none" }}
        >
          {/* Canvas wrapper — sticky so graph remains visible behind chat */}
          <div className="sticky top-0 shrink-0 z-[0]" style={{ touchAction: "pan-y", height: "100%" }}>
            <MindscapeCanvas
              nodes={translatedNodes}
              edges={graphEdges}
              dark={dark}
              onNodeFocus={handleNodeFocus}
              focusedNodeId={focusedNodeId}
            />

            {/* ── Hero Content (fades out when node focused) ── */}
            <div
              className={`absolute inset-x-0 top-0 z-[2] px-6 pt-12 sm:pt-16 pointer-events-none transition-all duration-700 ease-out
                ${heroVisible ? "" : "-translate-y-[50vh] opacity-0"}`}
            >
              <div className="pointer-events-auto">
                <div className="flex items-center gap-4 mb-1">
                  <img
                    src="/avatar_sebastiaan.png"
                    alt="Sebastiaan den Boer"
                    className="w-14 h-14 sm:w-[72px] sm:h-[72px] rounded-full object-cover border-2 border-ink/[0.06] dark:border-white/10 shadow-md shrink-0 hover:border-accent transition-colors"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                  />
                  <h1 className="text-[clamp(2rem,5vw,3.2rem)] font-bold tracking-tight leading-[1.1] text-ink dark:text-white">
                    Sebastiaan<br />den Boer
                  </h1>
                </div>
                <p className="mt-2.5 text-[clamp(0.85rem,1.3vw,1rem)] text-ink/50 dark:text-white/50 max-w-[420px] leading-relaxed">
                  {t("ui.subtitle")}
                </p>
                <div className="flex gap-5 mt-4">
                  {[
                    { label: t("ui.linkedin"), href: "https://linkedin.com/in/svdenboer" },
                    { label: t("ui.github"), href: "https://github.com/Zaklamp02" },
                    { label: t("ui.email"), href: "mailto:sebastiaandenboer@gmail.com" },
                  ].map((link) => (
                    <a
                      key={link.label}
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[0.78rem] text-ink/30 dark:text-white/30 no-underline hover:text-accent dark:hover:text-accent transition-colors"
                    >
                      {link.label}
                    </a>
                  ))}
                  <a
                    href="#about-section"
                    className="text-[0.78rem] text-ink/20 dark:text-white/20 no-underline hover:text-ink/40 dark:hover:text-white/40 transition-colors italic"
                  >
                    {t("ui.about_arrow")}
                  </a>
                </div>
              </div>
            </div>

            {/* ── Scroll hint ── */}
            <span
              className={`absolute bottom-6 right-6 text-[0.6rem] text-ink/20 dark:text-white/20 z-[2] pointer-events-none
                ${heroVisible ? "animate-fade-pulse" : "opacity-0"} transition-opacity duration-500`}
              style={{ writingMode: "vertical-rl", letterSpacing: "0.1em" }}
            >
              {t("ui.scroll_for_more")}
            </span>
          </div>

          {/* ── Chat Messages (transparent bg — graph/particles visible behind) ── */}
          {inlineMessages.length > 0 && (
            <div className="relative z-[1] flex flex-col gap-2.5 px-6 py-4 max-w-[600px] min-h-[calc(100dvh-120px)]">

              {inlineMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`max-w-[88%] px-4 py-3 rounded-2xl text-[0.88rem] leading-relaxed animate-bubble-in
                    ${msg.role === "twin"
                      ? "self-start bg-white/80 dark:bg-white/[0.06] backdrop-blur-lg border border-ink/[0.06] dark:border-white/[0.06] rounded-bl-sm text-ink dark:text-white"
                      : "self-end bg-accent text-white rounded-br-sm"
                    }`}
                >
                  {msg.role === "twin" && (
                    <div className="text-[0.6rem] font-semibold text-accent mb-1 tracking-wide">
                      {TWIN_NAME}
                    </div>
                  )}
                  {msg.content}
                </div>
              ))}
              {chat.loading && (
                <div className="self-start bg-white/80 dark:bg-white/[0.06] backdrop-blur-lg border border-ink/[0.06] dark:border-white/[0.06] rounded-2xl rounded-bl-sm px-4 py-3">
                  <div className="flex gap-1">
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Input Bar (floats over graph, doesn't consume layout space) ── */}
        <div className="absolute bottom-0 inset-x-0 z-[2] px-6 pb-3 pt-1 pointer-events-none">
          {/* Suggestion card — only visible on graph view (not when scrolled to chat) */}
          {focusedNodeTitle && !chat.loading && !scrolledToChat && (() => {
            const pc = PILLAR_COLORS[focusedPillarId ?? ""] ?? [45, 212, 191];
            return (
              <button
                onClick={() => handleSend(`${t("ui.tell_me_about")} ${focusedNodeTitle}`)}
                className="pointer-events-auto group flex items-center justify-between w-full max-w-[520px] mb-1.5 px-4 py-2 rounded-xl border text-left text-sm font-medium transition-all animate-slide-up cursor-pointer hover:scale-[1.01] active:scale-[0.99] backdrop-blur-md"
                style={{
                  borderColor: `rgba(${pc[0]},${pc[1]},${pc[2]},0.25)`,
                  backgroundColor: `rgba(${pc[0]},${pc[1]},${pc[2]},0.08)`,
                  color: `rgb(${pc[0]},${pc[1]},${pc[2]})`,
                }}
              >
                <span>{t("ui.tell_me_about")} {focusedNodeTitle}</span>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 ml-2 group-hover:translate-x-0.5 transition-transform">
                  <line x1="5" y1="12" x2="19" y2="12" />
                  <polyline points="12 5 19 12 12 19" />
                </svg>
              </button>
            );
          })()}
          <div className="pointer-events-auto flex items-center border border-ink/20 dark:border-white/20 rounded-2xl px-3.5 py-2.5 bg-white/80 dark:bg-gray-950/80 backdrop-blur-xl max-w-[520px] focus-within:border-accent focus-within:ring-[3px] focus-within:ring-accent/[0.08] transition-all">
            <input
              type="text"
              placeholder={t("ui.ask_anything")}
              className="flex-1 border-none outline-none font-[inherit] text-[0.95rem] text-ink dark:text-white bg-transparent placeholder:text-ink/20 dark:placeholder:text-white/20"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.currentTarget.value.trim()) {
                  handleSend(e.currentTarget.value.trim());
                  e.currentTarget.value = "";
                }
              }}
            />
            <button
              className={`w-[1.9rem] h-[1.9rem] rounded-full border-none flex items-center justify-center transition-all shrink-0 ${
                stt.recording
                  ? "bg-red-500 text-white animate-pulse"
                  : stt.transcribing
                  ? "bg-ink/10 dark:bg-white/10 text-ink/40 dark:text-white/40"
                  : "bg-transparent text-ink/30 dark:text-white/30 hover:text-accent dark:hover:text-accent hover:scale-105"
              }`}
              onClick={handleMic}
              aria-label={stt.recording ? "Stop recording" : "Voice input"}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </button>
            <button
              className="w-[1.9rem] h-[1.9rem] rounded-full bg-accent border-none text-white flex items-center justify-center opacity-50 hover:opacity-100 hover:scale-105 transition-all shrink-0"
              onClick={(e) => {
                const input = (e.currentTarget.parentElement?.querySelector('input') as HTMLInputElement);
                if (input?.value.trim()) {
                  handleSend(input.value.trim());
                  input.value = "";
                }
              }}
              aria-label="Send"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          BELOW THE FOLD
          ═══════════════════════════════════════════════════════════ */}

      {/* ── Blog / Curiosa ── */}
      <section id="blog-section" className="max-w-[720px] mx-auto px-6 pt-16 pb-8 snap-start">
        <h2 className="text-[0.7rem] tracking-[0.15em] uppercase text-ink/20 dark:text-white/20 mb-8">
          {t("ui.the_curiosa")}
        </h2>
        <div className="space-y-0">
          {[
            { date: "25 Apr 2026", title: "Docker DNS aliases can silently hijack your other services", excerpt: "Found out the hard way: if two Docker Compose stacks share a network and both have a service named \"frontend\"...", tags: ["TIL", "Docker"] },
            { date: "22 Apr 2026", title: "Why I built my own digital twin instead of using a template", excerpt: "Every AI chatbot builder promises \"your personal assistant in 5 minutes.\"...", tags: ["AI", "Projects"] },
          ].map((post, i) => (
            <div key={i} className="py-5 border-b border-ink/[0.06] dark:border-white/[0.06] last:border-b-0">
              <div className="text-[0.7rem] text-ink/20 dark:text-white/20">{post.date}</div>
              <div className="text-[0.95rem] font-semibold text-ink dark:text-white mt-1">{post.title}</div>
              <p className="text-[0.8rem] text-ink/50 dark:text-white/50 mt-1.5 leading-relaxed">{post.excerpt}</p>
              <div className="flex gap-2 mt-2">
                {post.tags.map((tag) => (
                  <span key={tag} className="text-[0.65rem] px-2 py-0.5 rounded-full bg-accent/[0.08] text-accent font-medium">{tag}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <a href="#" className="inline-block mt-6 text-[0.8rem] text-ink/20 dark:text-white/20 pointer-events-none">{t("ui.more_posts_coming")}</a>
      </section>

      {/* ── Projects ── */}
      <section id="projects-section" className="max-w-[720px] mx-auto px-6 pb-8 snap-start">
        <h2 className="text-[0.7rem] tracking-[0.15em] uppercase text-ink/20 dark:text-white/20 mb-8">
          {t("ui.projects_heading")}
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {[
            { title: "StoryBrew", tag: "Web app · dromenbrouwer.nl", desc: "AI-powered interactive story platform. Generative AI meets narrative design.", href: "https://dromenbrouwer.nl" },
            { title: "Digital Twin", tag: "This site · FastAPI + React", desc: "RAG-powered AI agent with knowledge graph, multi-tier access, and Telegram.", href: "https://github.com/Zaklamp02/digitaltwin" },
            { title: "RealLifeRisk", tag: "R/Shiny · Board game", desc: "Companion app for a physical strategy game. Move validation over local WiFi.", href: "https://github.com/Zaklamp02/RealLifeRisk" },
            { title: "Woodworking", tag: "Physical · Ongoing", desc: "Built a full kitchen from scratch. Currently: bespoke cabinet with reading nook." },
          ].map((proj) => (
            <a
              key={proj.title}
              href={proj.href ?? "#"}
              target={proj.href ? "_blank" : undefined}
              rel={proj.href ? "noopener noreferrer" : undefined}
              className="block border border-ink/[0.06] dark:border-white/[0.06] rounded-xl p-5 no-underline text-ink dark:text-white hover:border-accent hover:shadow-md transition-all"
            >
              <h3 className="text-[0.95rem] font-semibold">{proj.title}</h3>
              <div className="text-[0.7rem] text-accent mt-0.5">{proj.tag}</div>
              <p className="text-[0.8rem] text-ink/50 dark:text-white/50 mt-2 leading-relaxed">{proj.desc}</p>
            </a>
          ))}
        </div>
      </section>

      {/* ── About ── */}
      <section id="about-section" className="max-w-[720px] mx-auto px-6 py-16 snap-start">
        <h2 className="text-[0.7rem] tracking-[0.15em] uppercase text-ink/20 dark:text-white/20 mb-8">
          {t("about.heading")}
        </h2>
        <div className="flex flex-col sm:flex-row gap-8 items-center sm:items-start">
          <img
            src="/avatar_sebastiaan.png"
            alt="Sebastiaan den Boer"
            className="w-[120px] h-[120px] sm:w-[140px] sm:h-[140px] rounded-full sm:rounded-xl object-cover border-2 border-ink/[0.06] dark:border-white/10 shadow-lg shrink-0 hover:border-accent transition-colors"
          />
          <div className="text-center sm:text-left">
            <h3 className="text-lg font-semibold text-ink dark:text-white">{t("about.hi")}</h3>
            <p className="text-[0.88rem] text-ink/50 dark:text-white/50 leading-relaxed mt-2">
              {t("about.p1")}
            </p>
            <p className="text-[0.88rem] text-ink/50 dark:text-white/50 leading-relaxed mt-3">
              {t("about.p2")}
            </p>
            <p className="text-[0.88rem] text-ink/50 dark:text-white/50 leading-relaxed mt-3">
              {t("about.p3_prefix")} {TWIN_NAME} {t("about.p3_suffix")}
            </p>
            <div className="flex flex-wrap gap-1.5 mt-4 justify-center sm:justify-start">
              {["AI Strategy", "Data Science", "Leadership", "Woodworking", "MBA", "Python", "LLMs"].map((tag) => (
                <span key={tag} className="text-[0.65rem] px-2.5 py-1 rounded-full bg-accent/[0.08] text-accent font-medium">{tag}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="text-center py-12 text-[0.7rem] text-ink/20 dark:text-white/20">
        © {new Date().getFullYear()} Sebastiaan den Boer · {t("about.footer")}
      </footer>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════
   Full-screen chat (standalone /chat route)
   ══════════════════════════════════════════════════════════════════════ */

function FullChat({
  token,
  dark,
  setDark,
  language,
  setLanguage,
  onBack,
  onAdmin: _onAdmin,
}: {
  token: string;
  dark: boolean;
  setDark: (v: boolean) => void;
  language: "nl" | "en" | null;
  setLanguage: (v: "nl" | "en" | null) => void;
  onBack: () => void;
  onAdmin: () => void;
}) {
  const [inputMode, setInputMode] = useState<"voice" | "text">("text");
  const [injectedInput, setInjectedInput] = useState<string>("");

  const { t } = useTranslation(language, token);

  const ttsEnabled = inputMode === "voice";
  const tts = useTTS(token, ttsEnabled);

  const chat = useChat({
    token,
    language,
    onSentence: (sentence) => tts.enqueue(sentence),
    onConversationEnd: () => {},
  });

  const stt = useSTT(token);

  const handleMic = async () => {
    const transcript = await stt.toggle();
    if (transcript) {
      setInputMode("voice");
      setInjectedInput(transcript);
    }
  };

  const headerStatus = useMemo(() => {
    if (chat.error) return <span className="text-red-500">Error: {chat.error}</span>;
    if (chat.loading) return <span className="text-ink/40 dark:text-white/40">{t("ui.thinking")}</span>;
    if (stt.transcribing) return <span className="text-ink/40 dark:text-white/40">{t("ui.transcribing")}</span>;
    if (stt.recording) return <span className="text-red-500">● {t("ui.recording")}</span>;
    return null;
  }, [chat.error, chat.loading, stt.transcribing, stt.recording]);

  const newConversation = () => {
    tts.stop();
    chat.reset();
    setInputMode("text");
  };

  useEffect(() => {
    const onPopState = () => {
      if (window.location.pathname !== "/chat") onBack();
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [onBack]);

  return (
    <div className="mx-auto flex h-[100dvh] w-full max-w-[720px] flex-col bg-paper dark:bg-gray-950">
      <header className="flex items-center gap-3 px-4 py-3 border-b border-ink/10 dark:border-white/10 bg-white dark:bg-gray-900">
        <button
          onClick={onBack}
          className="h-9 w-9 rounded-full border border-ink/10 dark:border-white/10 bg-white dark:bg-white/5 flex items-center justify-center text-ink/60 dark:text-white/60 hover:text-accent dark:hover:text-accent transition-colors"
          aria-label="Back to home"
          title="Back to home"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div className="h-9 w-9 rounded-full bg-accent/10 overflow-hidden shrink-0 flex items-center justify-center">
          <img
            src="/avatar_digitaltwin.png"
            alt="Digital Twin"
            className="h-full w-full object-cover"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
          />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold leading-tight dark:text-white">{TWIN_NAME}</div>
          <div className="text-[11px] text-ink/50 dark:text-white/40 leading-tight h-4">{headerStatus}</div>
        </div>
        <button
          onClick={() => setLanguage(language === "nl" ? "en" : "nl")}
          className="h-8 px-2.5 rounded-full border border-ink/10 dark:border-white/10 bg-white dark:bg-white/5 flex items-center justify-center text-xs font-semibold text-ink/60 dark:text-white/60 hover:text-accent dark:hover:text-accent transition-colors"
          aria-label={language === "nl" ? t("ui.switch_to_english") : t("ui.switch_to_dutch")}
          title={language === "nl" ? t("ui.switch_to_english") : t("ui.switch_to_dutch")}
        >
          {language === "nl" ? "NL" : "EN"}
        </button>
        <button
          onClick={() => setDark(!dark)}
          className="h-8 w-8 rounded-full border border-ink/10 dark:border-white/10 bg-white dark:bg-white/5 flex items-center justify-center text-ink/60 dark:text-white/60 hover:text-accent dark:hover:text-accent transition-colors"
          aria-label={dark ? t("ui.light_mode") : t("ui.dark_mode")}
          title={dark ? t("ui.light_mode") : t("ui.dark_mode")}
        >
          {dark ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
              <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
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
        t={t}
      />

      {chat.conversationEnded ? (
        <ConversationEnd message={chat.conversationEndMessage} onNew={newConversation} t={t} />
      ) : (
        <InputBar
          disabled={chat.conversationEnded}
          loading={chat.loading}
          recording={stt.recording}
          transcribing={stt.transcribing}
          injected={injectedInput}
          onSend={(text) => {
            setInputMode("text");
            setInjectedInput("");
            void chat.send(text);
          }}
          onMic={handleMic}
          t={t}
        />
      )}
    </div>
  );
}
