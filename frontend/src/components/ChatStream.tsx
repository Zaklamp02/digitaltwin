import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github.css";
import type { ChatMessage } from "../hooks/useChat";

interface Props {
  messages: ChatMessage[];
  onReplay?: (text: string) => void;
  onSend?: (text: string) => void;
  ttsEnabled: boolean;
  token?: string;
  t?: (key: string, fallback?: string) => string;
}

const QUICK_PROMPTS_FALLBACK = [
  { label: "Career arc", text: "Give me a quick summary of your career arc." },
  { label: "Side projects", text: "What are your most interesting side projects?" },
  { label: "AI perspective", text: "How do you think about AI and its role?" },
  { label: "Tech stack", text: "What's your preferred tech stack and why?" },
];

// Custom components for ReactMarkdown — render inside the bubble without extra padding
const mdComponents = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="text-lg font-bold mt-3 mb-1.5 first:mt-0">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="text-base font-bold mt-2.5 mb-1 first:mt-0">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="text-[15px] font-semibold mt-2 mb-1 first:mt-0">{children}</h3>
  ),
  h4: ({ children }: { children?: React.ReactNode }) => (
    <h4 className="text-[15px] font-medium mt-1.5 mb-0.5 first:mt-0">{children}</h4>
  ),
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="list-disc list-outside ml-4 mb-2 space-y-1">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="list-decimal list-outside ml-4 mb-2 space-y-1">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold">{children}</strong>
  ),
  em: ({ children }: { children?: React.ReactNode }) => (
    <em className="italic">{children}</em>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="underline text-indigo-600 hover:text-indigo-800"
    >
      {children}
    </a>
  ),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  img: (props: any) => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { node, ...rest } = props;
    return (
      <img
        {...rest}
        className="rounded-xl my-2 max-w-[240px] w-full shadow-sm border border-ink/10 block"
        loading="lazy"
      />
    );
  },
  hr: () => <hr className="border-ink/10 my-2" />,
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="border-l-2 border-ink/20 dark:border-white/20 pl-3 text-ink/70 dark:text-white/60 italic my-1">{children}</blockquote>
  ),
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-xs overflow-x-auto my-2 [&>code]:!bg-transparent [&>code]:!p-0">
      {children}
    </pre>
  ),
  code: ({ children, className, ...rest }: { children?: React.ReactNode; className?: string; [key: string]: unknown }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) return <code className={className} {...(rest as object)}>{children}</code>;
    return <code className="bg-ink/5 dark:bg-white/10 rounded px-1 py-0.5 text-xs font-mono">{children}</code>;
  },
};

/** Display-only chat stream. Auto-scrolls on new content. */
export function ChatStream({ messages, onReplay, onSend, ttsEnabled, token, t: tProp }: Props) {
  const t = tProp ?? ((k: string, fb?: string) => fb ?? k);
  const endRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [chips, setChips] = useState(QUICK_PROMPTS_FALLBACK);
  const [welcomeMessage, setWelcomeMessage] = useState(
    "Hey! I'm Sebastiaan's digital twin. Ask me about my experience, projects, or how I think about AI."
  );

  // Fetch welcome message + chips from content-config, then fall back to /api/suggestions
  useEffect(() => {
    const headers: Record<string, string> = {};
    if (token) headers["X-Access-Token"] = token;

    // First try the content-config endpoint (admin-configurable)
    fetch("/api/content-config", { headers })
      .then((r) => r.json())
      .then((data: { welcome_message?: string; chips?: { label: string; text: string }[] }) => {
        if (data.welcome_message) setWelcomeMessage(data.welcome_message);
        if (data.chips && data.chips.length > 0) {
          setChips(data.chips.filter((c) => c.label && c.text));
          return; // chips from content-config take priority; skip /api/suggestions
        }
        // Fall through to suggestions endpoint
        return fetch("/api/suggestions", { headers })
          .then((r) => r.json())
          .then((s: { suggestions?: string[] }) => {
            if (s.suggestions && s.suggestions.length > 0) {
              setChips(s.suggestions.map((text) => ({
                label: text.split(" ").slice(0, 4).join(" ").replace(/[?.]$/, ""),
                text,
              })));
            }
          });
      })
      .catch(() => { /* fallback chips remain */ });
  }, [token]);

  // Track whether user has scrolled away from bottom
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 60;
      setShowScrollBtn(!atBottom);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Auto-scroll only if user is near the bottom
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 80;
    if (atBottom) {
      endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages]);

  const scrollToBottom = () => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    setShowScrollBtn(false);
  };

  const copyMessage = (id: string, text: string) => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 1500);
    });
  };

  const WELCOME = welcomeMessage;

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={scrollRef} className="chat-scroll h-full overflow-y-auto px-4 py-4">
      <div className="flex flex-col justify-end min-h-full space-y-4">
      {/* Always show a welcome bubble */}
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-2xl rounded-bl-md px-4 py-3 text-[15px] leading-relaxed bg-white dark:bg-gray-800 border border-ink/10 dark:border-white/10 text-ink dark:text-white shadow-sm">
          {WELCOME}
        </div>
      </div>
      {/* Quick-access suggestion chips — visible only before conversation starts */}
      {messages.length === 0 && onSend && (
        <div className="flex flex-wrap gap-2 pt-1 pb-2">
          {chips.map((p) => (
            <button
              key={p.label}
              onClick={() => onSend(p.text)}
              className="rounded-full border border-ink/15 dark:border-white/15 bg-white dark:bg-gray-800 px-3.5 py-1.5 text-sm text-ink/70 dark:text-white/60 hover:border-accent hover:text-accent transition-colors shadow-sm"
            >
              {p.label}
            </button>
          ))}
        </div>
      )}
      {messages.map((m) => {
        const isUser = m.role === "user";
        return (
          <div key={m.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
            <div
              className={[
                "max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed",
                isUser
                  ? "bg-accent text-white rounded-br-md whitespace-pre-wrap"
                  : "bg-white dark:bg-gray-800 border border-ink/10 dark:border-white/10 text-ink dark:text-white rounded-bl-md shadow-sm",
              ].join(" ")}
            >
              {isUser ? (
                <div>
                  {m.content}
                  {m.streaming && (
                    <span className="inline-block w-1.5 h-4 align-middle ml-0.5 bg-white/60 animate-pulse" />
                  )}
                </div>
              ) : (
                <div>
                  {m.streaming && !m.content ? (
                    /* Typing indicator — three bouncing dots */
                    <span className="flex items-center gap-1 h-5 text-ink/40 dark:text-white/40">
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                    </span>
                  ) : (
                    <>
                      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={mdComponents as any}>
                        {m.content}
                      </ReactMarkdown>
                      {m.streaming && (
                        <span className="inline-block w-1.5 h-4 align-middle ml-0.5 bg-ink/40 dark:bg-white/40 animate-pulse" />
                      )}
                    </>
                  )}
                </div>
              )}
              {!isUser && !m.streaming && m.content && (
                <div className="mt-2 flex items-center gap-3">
                  {ttsEnabled && onReplay && (
                    <button
                      className="text-[11px] text-ink/40 dark:text-white/40 hover:text-accent transition-colors"
                      onClick={() => onReplay(m.content)}
                      aria-label="Replay audio"
                    >
                      {t("ui.play", "▶︎ play")}
                    </button>
                  )}
                  <button
                    className="text-[11px] text-ink/40 dark:text-white/40 hover:text-accent transition-colors"
                    onClick={() => copyMessage(m.id, m.content)}
                    aria-label="Copy message"
                  >
                    {copiedId === m.id ? t("ui.copied", "✓ copied") : t("ui.copy", "⎘ copy")}
                  </button>
                </div>
              )}
            </div>
          </div>
        );
      })}
      <div ref={endRef} />
      </div>
      </div>
      {/* Scroll-to-bottom button — appears when user scrolls up */}
      {showScrollBtn && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-4 right-4 z-10 flex items-center justify-center w-9 h-9 rounded-full bg-white dark:bg-gray-800 border border-ink/15 dark:border-white/15 shadow-md text-ink/60 dark:text-white/60 hover:text-accent hover:border-accent transition-colors"
          aria-label="Scroll to bottom"
        >
          ↓
        </button>
      )}
    </div>
  );
}
