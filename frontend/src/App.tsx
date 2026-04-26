import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Admin } from "./components/Admin";
import { ChatStream } from "./components/ChatStream";
import { ConversationEnd } from "./components/ConversationEnd";
import { InputBar } from "./components/InputBar";
import { MindscapeCanvas, GraphNode, GraphEdge } from "./components/MindscapeCanvas";
import { useChat } from "./hooks/useChat";
import { useSTT } from "./hooks/useSTT";
import { useTTS } from "./hooks/useTTS";

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

/** Containment edge types — same set as in MindscapeCanvas */
const CONTAINMENT_EDGE_TYPES = new Set(["has", "includes", "nb_page", "member_of", "studied_at"]);

/** Rich opener messages per node id */
const CHAT_OPENERS: Record<string, string> = {
  career:      "Career — Sebastiaan moved from hands-on data science to directing AI strategy at scale. The executive MBA bridged the tech/business gap. What angle interests you?",
  education:   "Education — neuroscience BSc, a brief detour through software engineering, then an executive MBA. Each step was deliberate. What would you like to know?",
  hobbies:     "Beyond work — woodworking (built a full kitchen from scratch!), running (slowly but consistently), cooking, and far too many board games. Ask me anything!",
  community:   "Community — aiGrunn meetups, conference talks, and open-source contributions. Sebastiaan believes expertise only compounds when shared. What interests you?",
  personality: "Values — craftsmanship, curiosity, radical honesty. Not wall-poster words but actual constraints on how he works and leads. What resonates?",
  "nb-work":   "Work notebook — a running log of roles, projects, and lessons from Philips to FIOD to Youwe. Ask about any chapter.",
};

/** Type-aware opener fallback for nodes not in CHAT_OPENERS */
function getOpenerForNode(nodeId: string, title: string, nodes: GraphNode[]): string {
  const hardcoded = CHAT_OPENERS[nodeId];
  if (hardcoded) return hardcoded;
  const node = nodes.find((n) => n.id === nodeId);
  switch (node?.type) {
    case "job":       return `${title} — a role in Sebastiaan's career. Ask about what he built there, the team, the challenges, or what he'd do differently.`;
    case "project":   return `${title} — one of Sebastiaan's projects. What do you want to know? Tech stack, origin story, current status…`;
    case "skill":     return `${title} — part of the toolkit. Ask how he uses it, what he's built with it, or how it fits into the bigger picture.`;
    case "education": return `${title} — ask about what Sebastiaan studied, what stuck, and how it shaped how he thinks today.`;
    case "personal":  return `${title} — life beyond the keyboard. Ask Sebastiaan anything about this.`;
    case "community": return `${title} — Sebastiaan's community work. Ask about events, talks, or his involvement.`;
    case "opinion":   return `${title} — Sebastiaan has views here. Ask him to share his perspective.`;
    default:          return `You're exploring ${title}. What would you like to know?`;
  }
}

/** Generate 2–3 quick-tap suggestion chips for a focused node */
function getSuggestionsForNode(
  nodeId: string,
  nodes: GraphNode[],
  edges: GraphEdge[],
): string[] {
  // Child nodes (containment edges)
  const childIds = edges
    .filter((e) => e.source === nodeId && CONTAINMENT_EDGE_TYPES.has(e.type))
    .map((e) => e.target)
    .slice(0, 5);
  const children = childIds
    .map((id) => nodes.find((n) => n.id === id))
    .filter((n): n is GraphNode => n !== undefined);

  if (children.length >= 2) {
    return children.slice(0, 3).map((c) => `Tell me about ${c.title}`);
  }

  // Fallback: type-specific generic questions
  const node = nodes.find((n) => n.id === nodeId);
  switch (node?.type) {
    case "job":
      return ["What did you build here?", "What were the biggest challenges?", "Who was on your team?"];
    case "project":
      return ["What's the tech stack?", "What was the hardest part?", "Is this still active?"];
    case "education":
      return ["What was the most valuable thing you learned?", "How did this shape your career?"];
    case "personal":
      return ["Tell me more", "How did you get into this?"];
    case "community":
      return ["What events have you organised?", "What topics do you speak about?"];
    default:
      return ["Tell me more", "What's the most interesting part?"];
  }
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

  /* ── Focus state ── */
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [heroVisible, setHeroVisible] = useState(true);
  const [chatActive, setChatActive] = useState(false);

  /* ── Chat ── */
  const chat = useChat({ token, language, onConversationEnd: () => {} });
  const stt = useSTT(token);
  const [inlineMessages, setInlineMessages] = useState<
    { id: string; role: "user" | "twin"; content: string }[]
  >([]);
  const [inlineSuggestions, setInlineSuggestions] = useState<string[]>([]);

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
    (node: { id: string; title: string } | null) => {
      if (node) {
        setFocusedNodeId(node.id);
        setHeroVisible(false);
        setChatActive(true);
        setInlineMessages([]);
        setInlineSuggestions([]);
        chat.reset();
        const opener = getOpenerForNode(node.id, node.title, graphNodes);
        const suggestions = getSuggestionsForNode(node.id, graphNodes, graphEdges);
        setTimeout(() => {
          addTwinMessage(opener);
          setInlineSuggestions(suggestions);
        }, 350);
      } else {
        setFocusedNodeId(null);
        setInlineMessages([]);
        setInlineSuggestions([]);
        setHeroVisible(true);
        setChatActive(false);
        chat.reset();
      }
    },
    [addTwinMessage, chat, graphNodes, graphEdges],
  );

  const goHome = useCallback(() => {
    setFocusedNodeId(null);
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
      setInlineSuggestions([]); // dismiss chips once user starts talking
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

  /* ── Scroll chat ── */
  const chatAreaRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (chatAreaRef.current) {
      chatAreaRef.current.scrollTop = chatAreaRef.current.scrollHeight;
    }
  }, [inlineMessages]);

  return (
    <div className="min-h-[100dvh] bg-paper dark:bg-gray-950 transition-colors duration-500">
      {/* ════════════════════════════════════════════════════════════
          HERO SECTION (full viewport)
          ════════════════════════════════════════════════════════════ */}
      <div className="relative h-[100dvh] flex flex-col overflow-hidden" style={{ touchAction: "none" }}>
        {/* Canvas */}
        <MindscapeCanvas
          nodes={graphNodes}
          edges={graphEdges}
          dark={dark}
          onNodeFocus={handleNodeFocus}
          focusedNodeId={focusedNodeId}
        />

        {/* ── Settings button (top-right, always visible) ── */}
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
                <span>{dark ? "Light mode" : "Dark mode"}</span>
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
                <span>{language === "nl" ? "Switch to English" : "Switch to Dutch"}</span>
                <span className="text-xs font-semibold text-ink/40 dark:text-white/40">{language === "nl" ? "NL" : "EN"}</span>
              </button>

              <div className="h-px bg-ink/[0.06] dark:bg-white/10 my-1.5" />
            </div>
          )}
        </div>

        {/* ── Compact Header (slides in when hero leaves) ── */}
        <div
          className={`relative z-[3] flex items-center justify-between px-4 py-2.5
            bg-white/75 dark:bg-gray-950/75 backdrop-blur-xl border-b border-ink/[0.06] dark:border-white/[0.06]
            transition-all duration-600 ease-out
            ${heroVisible ? "-translate-y-full opacity-0 pointer-events-none" : "translate-y-0 opacity-100"}`}
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
            <a href="#blog-section" className="text-ink/30 dark:text-white/30 hover:text-accent dark:hover:text-accent transition-colors no-underline">Blog</a>
            <a href="#projects-section" className="text-ink/30 dark:text-white/30 hover:text-accent dark:hover:text-accent transition-colors no-underline">Projects</a>
            <a href="#about-section" className="text-ink/30 dark:text-white/30 hover:text-accent dark:hover:text-accent transition-colors no-underline">About</a>
            <a href="https://linkedin.com/in/svdenboer" target="_blank" rel="noopener noreferrer" className="text-ink/30 dark:text-white/30 hover:text-accent dark:hover:text-accent transition-colors no-underline">LinkedIn</a>
          </div>
        </div>

        {/* ── Hero Content (fades out when node focused) ── */}
        <div
          className={`relative z-[2] px-6 pt-12 sm:pt-16 pointer-events-none transition-all duration-700 ease-out
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
              I build AI systems that make high-stakes decisions better. Director of Data Science &amp; AI. Nerd with MBA.
            </p>
            <div className="flex gap-5 mt-4">
              {[
                { label: "LinkedIn", href: "https://linkedin.com/in/svdenboer" },
                { label: "GitHub", href: "https://github.com/Zaklamp02" },
                { label: "Email", href: "mailto:sebastiaandenboer@gmail.com" },
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
                About ↓
              </a>
            </div>
          </div>
        </div>

        {/* ── Inline Chat Messages ── */}
        <div
          ref={chatAreaRef}
          className="relative z-[2] flex-1 flex flex-col justify-end px-6 max-w-[600px] overflow-y-auto pointer-events-none"
          style={{ scrollbarWidth: "none" }}
        >
          <div className="flex flex-col gap-2.5 pb-2 pointer-events-auto">
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
            {chat.loading && inlineMessages.length > 0 && (
              <div className="self-start bg-white/80 dark:bg-white/[0.06] backdrop-blur-lg border border-ink/[0.06] dark:border-white/[0.06] rounded-2xl rounded-bl-sm px-4 py-3">
                <div className="flex gap-1">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            )}
            {/* ── Suggestion chips ── */}
            {inlineSuggestions.length > 0 && !chat.loading && (
              <div className="flex flex-wrap gap-1.5 pt-0.5">
                {inlineSuggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => handleSend(s)}
                    className="text-[0.76rem] px-3 py-1.5 rounded-full border border-accent/25 dark:border-accent/30 text-accent bg-accent/[0.05] dark:bg-accent/[0.08] hover:bg-accent/[0.12] hover:border-accent/50 transition-all"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Input Bar ── */}
        <div className="relative z-[2] px-6 pb-4 pt-2">
          <div className="text-[0.65rem] text-ink/20 dark:text-white/20 mb-1.5 tracking-widest uppercase">
            Ask {TWIN_NAME} anything
          </div>
          <div className="flex items-center border border-ink/20 dark:border-white/20 rounded-2xl px-3.5 py-2.5 bg-white/80 dark:bg-gray-950/80 backdrop-blur-xl max-w-[520px] focus-within:border-accent focus-within:ring-[3px] focus-within:ring-accent/[0.08] transition-all">
            <input
              type="text"
              placeholder={focusedNodeId ? `Ask about ${graphNodes.find(n => n.id === focusedNodeId)?.title ?? 'this topic'}…` : "What's your experience with AI agents?"}
              className="flex-1 border-none outline-none font-[inherit] text-[0.95rem] text-ink dark:text-white bg-transparent placeholder:text-ink/20 dark:placeholder:text-white/20"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.currentTarget.value.trim()) {
                  handleSend(e.currentTarget.value.trim());
                  e.currentTarget.value = "";
                }
              }}
              onMouseDown={(e) => e.stopPropagation()}
              onTouchStart={(e) => e.stopPropagation()}
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

        {/* ── Scroll hint ── */}
        <span
          className={`absolute bottom-24 right-6 text-[0.6rem] text-ink/20 dark:text-white/20 z-[2] pointer-events-none
            ${heroVisible ? "animate-fade-pulse" : "opacity-0"} transition-opacity duration-500`}
          style={{ writingMode: "vertical-rl", letterSpacing: "0.1em" }}
        >
          scroll for more
        </span>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          BELOW THE FOLD
          ═══════════════════════════════════════════════════════════ */}

      {/* ── Blog / Curiosa ── */}
      <section id="blog-section" className="max-w-[720px] mx-auto px-6 pt-16 pb-8">
        <h2 className="text-[0.7rem] tracking-[0.15em] uppercase text-ink/20 dark:text-white/20 mb-8">
          The Curiosa
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
        <a href="#" className="inline-block mt-6 text-[0.8rem] text-ink/20 dark:text-white/20 pointer-events-none">More posts coming soon</a>
      </section>

      {/* ── Projects ── */}
      <section id="projects-section" className="max-w-[720px] mx-auto px-6 pb-8">
        <h2 className="text-[0.7rem] tracking-[0.15em] uppercase text-ink/20 dark:text-white/20 mb-8">
          Projects
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
      <section id="about-section" className="max-w-[720px] mx-auto px-6 py-16">
        <h2 className="text-[0.7rem] tracking-[0.15em] uppercase text-ink/20 dark:text-white/20 mb-8">
          About
        </h2>
        <div className="flex flex-col sm:flex-row gap-8 items-center sm:items-start">
          <img
            src="/avatar_sebastiaan.png"
            alt="Sebastiaan den Boer"
            className="w-[120px] h-[120px] sm:w-[140px] sm:h-[140px] rounded-full sm:rounded-xl object-cover border-2 border-ink/[0.06] dark:border-white/10 shadow-lg shrink-0 hover:border-accent transition-colors"
          />
          <div className="text-center sm:text-left">
            <h3 className="text-lg font-semibold text-ink dark:text-white">Hi, I'm Sebastiaan</h3>
            <p className="text-[0.88rem] text-ink/50 dark:text-white/50 leading-relaxed mt-2">
              Director of Data Science &amp; AI by day, compulsive builder by night.
              I lead teams that turn messy data into decisions that actually matter —
              from fraud detection to supply chain optimisation.
            </p>
            <p className="text-[0.88rem] text-ink/50 dark:text-white/50 leading-relaxed mt-3">
              When I'm not wrangling models, I'm building furniture from scratch (full kitchen, done),
              running (slowly), or hosting overly competitive board game nights.
            </p>
            <p className="text-[0.88rem] text-ink/50 dark:text-white/50 leading-relaxed mt-3">
              This site is my digital twin — an AI agent trained on my professional and personal knowledge.
              Ask {TWIN_NAME} anything, or explore the mind map above.
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
        © {new Date().getFullYear()} Sebastiaan den Boer · Built with too many Docker containers
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
    if (chat.loading) return <span className="text-ink/40 dark:text-white/40">Thinking…</span>;
    if (stt.transcribing) return <span className="text-ink/40 dark:text-white/40">Transcribing…</span>;
    if (stt.recording) return <span className="text-red-500">● recording</span>;
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
          aria-label={language === "nl" ? "Switch to English" : "Switch to Dutch"}
          title={language === "nl" ? "Switch to English" : "Switch to Dutch"}
        >
          {language === "nl" ? "NL" : "EN"}
        </button>
        <button
          onClick={() => setDark(!dark)}
          className="h-8 w-8 rounded-full border border-ink/10 dark:border-white/10 bg-white dark:bg-white/5 flex items-center justify-center text-ink/60 dark:text-white/60 hover:text-accent dark:hover:text-accent transition-colors"
          aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
          title={dark ? "Light mode" : "Dark mode"}
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
            setInputMode("text");
            setInjectedInput("");
            void chat.send(t);
          }}
          onMic={handleMic}
        />
      )}
    </div>
  );
}
