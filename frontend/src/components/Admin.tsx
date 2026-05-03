/**
 * Admin dashboard — personal-tier only.
 * Accessed via: http://localhost:5173/?page=admin&t=<personal-token>
 *
 * Tabs: Overview | Logs | Knowledge | Graph | Config | Roles & Access | Sessions | Eval
 */
import { useCallback, useEffect, useRef, useState } from "react";
import KnowledgeTab from "./knowledge/KnowledgeTabNotebook";
import GraphTab from "./GraphTab";
import TranslationsTab from "./TranslationsTab";

// ── types ─────────────────────────────────────────────────────────────────────

interface Stats {
  conversations_today: number;
  conversations_week: number;
  conversations_total: number;
  turns_today: number;
  avg_turns_per_conversation: number;
  tier_breakdown: Record<string, number>;
  token_input_today: number;
  token_output_today: number;
  token_input_total: number;
  token_output_total: number;
  cost_estimate_usd: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  avg_ttft_ms: number;
  p95_ttft_ms: number;
  timeline: { date: string; conversations: number }[];
  model_breakdown: Record<string, number>;
}

interface LogEntry {
  ts: string;
  event: string;
  session_id?: string;
  tier?: string;
  turn?: number;
  latency_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  chunks?: { file: string; section: string; score: number; tier: string }[];
  [key: string]: unknown;
}

interface AdminConfig {
  llm_provider: string;
  model_name: string;
  embedding_provider: string;
  embedding_model: string;
  rag_top_k: number;
  rag_min_score: number;
  rag_context_turns: number;
  chunk_tokens: number;
  chunk_overlap: number;
  tts_model: string;
  tts_voice: string;
  stt_model: string;
  rate_limit_enabled: boolean;
  allowed_models: Record<string, string[]>;
  tts_models: string[];
  stt_models: string[];
  tts_voices: string[];
  tts_voices_all: string[];
  tts_voices_basic: string[];
  tier_limits: Record<string, { conversations_per_day: number; turns_per_conversation: number }>;
}

interface Session {
  session_id: string;
  tier: string;
  ip_hash: string;
  turns: number;
  closed: boolean;
  started_ago_s: number;
}

type Tab = "overview" | "logs" | "content" | "knowledge" | "graph" | "config" | "roles" | "sessions" | "eval" | "translations";

// ── helpers ───────────────────────────────────────────────────────────────────

const TIER_COLORS: Record<string, string> = {
  public:    "bg-sky-400",
  work:      "bg-blue-400",
  friends:   "bg-pink-400",
  personal:  "bg-emerald-400",
  // legacy
  recruiter: "bg-blue-400",
};
const TIER_TEXT: Record<string, string> = {
  public:    "text-sky-700",
  work:      "text-blue-700",
  friends:   "text-pink-700",
  personal:  "text-emerald-700",
  recruiter: "text-blue-700",
};
const TIER_BG: Record<string, string> = {
  public:    "bg-sky-50 border-sky-200",
  work:      "bg-blue-50 border-blue-200",
  friends:   "bg-pink-50 border-pink-200",
  personal:  "bg-emerald-50 border-emerald-200",
  recruiter: "bg-blue-50 border-blue-200",
};

function fmtAgo(s: number): string {
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

function fmtTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString("nl-NL", { timeZone: "Europe/Amsterdam" });
  } catch {
    return ts;
  }
}

function fmtNum(n: number): string {
  return n.toLocaleString();
}

// ── sub-components ────────────────────────────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="text-2xl font-bold text-gray-900">{typeof value === "number" ? fmtNum(value) : value}</div>
      <div className="text-sm text-gray-500 mt-0.5">{label}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  );
}

function TierBadge({ tier }: { tier: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${TIER_BG[tier] ?? "bg-gray-50 border-gray-200 text-gray-600"} ${TIER_TEXT[tier] ?? "text-gray-600"}`}>
      {tier}
    </span>
  );
}

function Sparkline({ data }: { data: { date: string; conversations: number }[] }) {
  const max = Math.max(...data.map((d) => d.conversations), 1);
  const W = 600;
  const H = 60;
  const pad = 4;
  const step = (W - pad * 2) / (data.length - 1);
  const y = (v: number) => H - pad - ((v / max) * (H - pad * 2));

  const points = data.map((d, i) => `${pad + i * step},${y(d.conversations)}`).join(" ");
  const fill = `${points} ${pad + (data.length - 1) * step},${H} ${pad},${H}`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-16" preserveAspectRatio="none">
      <polygon points={fill} className="fill-indigo-100" />
      <polyline points={points} className="fill-none stroke-indigo-500" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function TierBar({ breakdown }: { breakdown: Record<string, number> }) {
  const total = Object.values(breakdown).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="flex rounded-full overflow-hidden h-4 w-full gap-px">
      {Object.entries(breakdown).map(([tier, count]) => (
        <div
          key={tier}
          className={TIER_COLORS[tier] ?? "bg-gray-300"}
          style={{ width: `${(count / total) * 100}%` }}
          title={`${tier}: ${count}`}
        />
      ))}
    </div>
  );
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function OverviewTab({ stats }: { stats: Stats }) {
  const totalBreakdown = Object.values(stats.tier_breakdown).reduce((a, b) => a + b, 0) || 1;

  return (
    <div className="space-y-6">
      {/* Primary stats */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">Conversations</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Today" value={stats.conversations_today} />
          <StatCard label="This week" value={stats.conversations_week} />
          <StatCard label="All time" value={stats.conversations_total} />
          <StatCard label="Avg turns / conv" value={stats.avg_turns_per_conversation} sub={`${stats.turns_today} turns today`} />
        </div>
      </div>

      {/* Token / cost stats */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">Token usage</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Input tokens today" value={fmtNum(stats.token_input_today)} />
          <StatCard label="Output tokens today" value={fmtNum(stats.token_output_today)} />
          <StatCard label="Total tokens (all time)" value={fmtNum(stats.token_input_total + stats.token_output_total)} />
          <StatCard label="Est. cost (all time)" value={`$${stats.cost_estimate_usd.toFixed(4)}`} sub="~$2/M in · $8/M out" />
        </div>
      </div>

      {/* Latency */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">Latency</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Avg TTFT" value={`${stats.avg_ttft_ms} ms`} sub="time to first token" />
          <StatCard label="p95 TTFT" value={`${stats.p95_ttft_ms} ms`} sub="time to first token" />
          <StatCard label="Avg stream time" value={`${stats.avg_latency_ms} ms`} sub="full response duration" />
          <StatCard label="p95 stream time" value={`${stats.p95_latency_ms} ms`} sub="full response duration" />
        </div>
      </div>

      {/* Timeline */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-700">Conversations — last 30 days</h3>
        </div>
        <Sparkline data={stats.timeline} />
        <div className="flex justify-between text-[10px] text-gray-400 mt-1">
          <span>{stats.timeline[0]?.date}</span>
          <span>{stats.timeline[stats.timeline.length - 1]?.date}</span>
        </div>
      </div>

      {/* Tier breakdown */}
      <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Tier breakdown (unique conversations)</h3>
        <TierBar breakdown={stats.tier_breakdown} />
        <div className="flex gap-4 mt-3 flex-wrap">
          {Object.entries(stats.tier_breakdown).map(([tier, count]) => (
            <div key={tier} className="flex items-center gap-1.5 text-sm">
              <div className={`h-3 w-3 rounded-full ${TIER_COLORS[tier] ?? "bg-gray-300"}`} />
              <span className="text-gray-600">{tier}</span>
              <span className="font-semibold text-gray-800">{count}</span>
              <span className="text-gray-400">({Math.round((count / totalBreakdown) * 100)}%)</span>
            </div>
          ))}
        </div>
      </div>

      {/* Model breakdown */}
      {Object.keys(stats.model_breakdown).length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Model usage</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                <th className="pb-2">Model</th>
                <th className="pb-2 text-right">Requests</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.model_breakdown)
                .sort(([, a], [, b]) => b - a)
                .map(([model, count]) => (
                  <tr key={model} className="border-b border-gray-50 last:border-0">
                    <td className="py-1.5 font-mono text-xs text-gray-700">{model}</td>
                    <td className="py-1.5 text-right text-gray-900 font-medium">{count}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Logs tab ──────────────────────────────────────────────────────────────────

function LogsTab({ token }: { token: string }) {
  const [logs, setLogs] = useState<{ total: number; entries: LogEntry[] } | null>(null);
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const limit = 30;

  const load = useCallback(async (off: number) => {
    const res = await fetch(`/api/admin/logs?limit=${limit}&offset=${off}`, {
      headers: { "X-Access-Token": token },
    });
    if (res.ok) setLogs(await res.json());
  }, [token]);

  useEffect(() => { load(offset); }, [load, offset]);

  if (!logs) return <div className="text-gray-400 text-sm py-8 text-center">Loading…</div>;

  const toggleExpand = (i: number) => {
    setExpanded((prev) => {
      const n = new Set(prev);
      n.has(i) ? n.delete(i) : n.add(i);
      return n;
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-500">{fmtNum(logs.total)} total entries</span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
            className="px-3 py-1.5 text-sm rounded-lg border border-gray-200 disabled:opacity-40 hover:bg-gray-50"
          >
            ← Newer
          </button>
          <button
            disabled={offset + limit >= logs.total}
            onClick={() => setOffset(offset + limit)}
            className="px-3 py-1.5 text-sm rounded-lg border border-gray-200 disabled:opacity-40 hover:bg-gray-50"
          >
            Older →
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr className="text-left text-xs text-gray-400 uppercase tracking-wider">
              <th className="px-4 py-2.5">Timestamp</th>
              <th className="px-4 py-2.5">Event</th>
              <th className="px-4 py-2.5">Tier</th>
              <th className="px-4 py-2.5">Turn</th>
              <th className="px-4 py-2.5">Latency</th>
              <th className="px-4 py-2.5">Tokens in / out</th>
              <th className="px-4 py-2.5 w-8" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {logs.entries.map((e, i) => (
              <>
                <tr
                  key={i}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => toggleExpand(i)}
                >
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-500 whitespace-nowrap">{fmtTs(e.ts)}</td>
                  <td className="px-4 py-2.5">
                    <span className={`font-mono text-xs px-1.5 py-0.5 rounded ${e.event === "chat" ? "bg-indigo-50 text-indigo-700" : "bg-red-50 text-red-700"}`}>
                      {e.event}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">{e.tier ? <TierBadge tier={e.tier} /> : "—"}</td>
                  <td className="px-4 py-2.5 text-gray-700">{e.turn ?? "—"}</td>
                  <td className="px-4 py-2.5 text-gray-700">{e.latency_ms != null ? `${e.latency_ms} ms` : "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-600">
                    {e.input_tokens != null ? `${e.input_tokens} / ${e.output_tokens ?? 0}` : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-gray-400 text-xs">{expanded.has(i) ? "▲" : "▼"}</td>
                </tr>
                {expanded.has(i) && (
                  <tr key={`exp-${i}`}>
                    <td colSpan={7} className="px-4 py-3 bg-gray-50">
                      <pre className="text-xs text-gray-600 overflow-x-auto whitespace-pre-wrap break-all font-mono bg-white rounded border border-gray-200 p-3">
                        {JSON.stringify(e, null, 2)}
                      </pre>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Content tab ───────────────────────────────────────────────────────────────

interface ContentConfig {
  welcome_message: string;
  system_prompt: string;
  chips: { label: string; text: string }[];
}

function ContentTab({ token }: { token: string }) {
  const [cfg, setCfg] = useState<ContentConfig | null>(null);
  const [welcome, setWelcome] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [chips, setChips] = useState<{ label: string; text: string }[]>([]);
  const [savingSection, setSavingSection] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Record<string, string>>({});

  const load = async () => {
    const res = await fetch("/api/admin/content", { headers: { "X-Access-Token": token } });
    if (res.ok) {
      const data: ContentConfig = await res.json();
      setCfg(data);
      setWelcome(data.welcome_message);
      setSystemPrompt(data.system_prompt);
      setChips(data.chips);
    }
  };

  useEffect(() => { void load(); }, [token]);

  const save = async (section: string, body: Partial<ContentConfig>) => {
    setSavingSection(section);
    const res = await fetch("/api/admin/content", {
      method: "PATCH",
      headers: { "X-Access-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setSavingSection(null);
    const data = await res.json().catch(() => ({}));
    setMsgs((m) => ({ ...m, [section]: res.ok ? "Saved ✓" : `Error: ${data.detail ?? "unknown"}` }));
    if (res.ok) setTimeout(() => setMsgs((m) => ({ ...m, [section]: "" })), 2500);
  };

  const updateChip = (i: number, field: "label" | "text", val: string) => {
    setChips((prev) => prev.map((c, idx) => idx === i ? { ...c, [field]: val } : c));
  };
  const addChip = () => setChips((prev) => [...prev, { label: "", text: "" }]);
  const removeChip = (i: number) => setChips((prev) => prev.filter((_, idx) => idx !== i));
  const moveChip = (i: number, dir: -1 | 1) => {
    setChips((prev) => {
      const next = [...prev];
      const j = i + dir;
      if (j < 0 || j >= next.length) return next;
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  if (!cfg) return <div className="text-gray-400 text-sm py-8 text-center">Loading…</div>;

  return (
    <div className="space-y-6 max-w-3xl">

      {/* Welcome message */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-1">Welcome message</h3>
        <p className="text-xs text-gray-400 mb-3">The first chat bubble the user sees when they open the chat.</p>
        <textarea
          rows={3}
          value={welcome}
          onChange={(e) => setWelcome(e.target.value)}
          className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="Hey! I'm Sebastiaan's digital twin…"
        />
        {/* Live preview */}
        <div className="mt-3 bg-gray-50 border border-gray-100 rounded-xl px-4 py-3 text-sm text-gray-700 max-w-[85%]">
          <span className="text-[10px] text-gray-400 uppercase tracking-wider block mb-1">Preview</span>
          {welcome || <span className="italic text-gray-400">Empty</span>}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={() => void save("welcome", { welcome_message: welcome })}
            disabled={savingSection === "welcome"}
            className="rounded-lg bg-indigo-600 text-white px-4 py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {savingSection === "welcome" ? "Saving…" : "Save welcome message"}
          </button>
          {msgs.welcome && <span className="text-sm text-emerald-600">{msgs.welcome}</span>}
        </div>
      </section>

      {/* System prompt */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-1">System prompt</h3>
        <p className="text-xs text-gray-400 mb-3">The hidden instruction sent to the LLM before every conversation. Controls tone, rules, and persona.</p>
        <textarea
          rows={18}
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-xs font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500"
          placeholder="You are Sebastiaan's digital twin…"
          spellCheck={false}
        />
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={() => void save("system", { system_prompt: systemPrompt })}
            disabled={savingSection === "system"}
            className="rounded-lg bg-indigo-600 text-white px-4 py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {savingSection === "system" ? "Saving…" : "Save system prompt"}
          </button>
          <button
            onClick={() => setSystemPrompt(cfg.system_prompt)}
            className="rounded-lg border border-gray-200 text-gray-500 px-4 py-2 text-sm hover:bg-gray-50 transition-colors"
          >
            Reset
          </button>
          {msgs.system && <span className="text-sm text-emerald-600">{msgs.system}</span>}
        </div>
      </section>

      {/* Suggestion chips */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-1">Suggestion chips</h3>
        <p className="text-xs text-gray-400 mb-4">Quick-action buttons shown below the welcome message. Up to 6 chips. Label = short button text; Question = what gets sent.</p>
        <div className="space-y-2">
          {chips.map((chip, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="flex flex-col gap-0.5">
                <button onClick={() => moveChip(i, -1)} disabled={i === 0} className="text-gray-300 hover:text-gray-500 disabled:opacity-20 text-xs leading-none">▲</button>
                <button onClick={() => moveChip(i, 1)} disabled={i === chips.length - 1} className="text-gray-300 hover:text-gray-500 disabled:opacity-20 text-xs leading-none">▼</button>
              </div>
              <input
                value={chip.label}
                onChange={(e) => updateChip(i, "label", e.target.value)}
                placeholder="Label"
                className="w-32 shrink-0 rounded-lg border border-gray-200 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-400"
              />
              <input
                value={chip.text}
                onChange={(e) => updateChip(i, "text", e.target.value)}
                placeholder="Question text sent to the AI…"
                className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-400"
              />
              <button onClick={() => removeChip(i)} className="text-gray-300 hover:text-red-400 text-sm px-1">✕</button>
            </div>
          ))}
        </div>
        {chips.length < 6 && (
          <button onClick={addChip} className="mt-3 text-sm text-indigo-600 hover:text-indigo-800">+ Add chip</button>
        )}
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={() => void save("chips", { chips })}
            disabled={savingSection === "chips"}
            className="rounded-lg bg-indigo-600 text-white px-4 py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {savingSection === "chips" ? "Saving…" : "Save chips"}
          </button>
          {msgs.chips && <span className="text-sm text-emerald-600">{msgs.chips}</span>}
        </div>
      </section>

    </div>
  );
}


// ── Config tab ────────────────────────────────────────────────────────────────

function ConfigTab({ token }: { token: string }) {
  const [cfg, setCfg] = useState<AdminConfig | null>(null);
  const [draft, setDraft] = useState<Partial<AdminConfig>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await fetch("/api/admin/config", { headers: { "X-Access-Token": token } });
    if (res.ok) {
      const data: AdminConfig = await res.json();
      setCfg(data);
      setDraft({
        llm_provider: data.llm_provider,
        model_name: data.model_name,
        rag_top_k: data.rag_top_k,
        rag_min_score: data.rag_min_score,
        rate_limit_enabled: data.rate_limit_enabled,
        tts_model: data.tts_model,
        tts_voice: data.tts_voice,
        stt_model: data.stt_model,
      });
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    setMsg(null);
    const res = await fetch("/api/admin/config", {
      method: "PATCH",
      headers: { "X-Access-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
    setSaving(false);
    if (res.ok) {
      const data = await res.json();
      setMsg(`Saved: ${data.changed.join(", ") || "no changes"}`);
      load();
    } else {
      const err = await res.json().catch(() => ({}));
      setMsg(`Error: ${err.detail ?? "unknown"}`);
    }
  };

  if (!cfg) return <div className="text-gray-400 text-sm py-8 text-center">Loading…</div>;

  return (
    <div className="space-y-6 max-w-2xl">
      {/* LLM */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-4">Language model</h3>
        <div className="space-y-4">
        <div>
            <label className="block text-xs text-gray-500 mb-1">Provider</label>
            <select
              value={draft.llm_provider ?? cfg.llm_provider}
              onChange={(e) => {
                const p = e.target.value;
                const firstModel = (cfg.allowed_models[p] ?? [])[0] ?? "";
                setDraft({ ...draft, llm_provider: p, model_name: firstModel });
              }}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            >
              {["anthropic", "openai", "ollama"].map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">Switching provider takes effect immediately after Save.</p>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Model</label>
            <select
              value={draft.model_name ?? cfg.model_name}
              onChange={(e) => setDraft({ ...draft, model_name: e.target.value })}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            >
              {((cfg.allowed_models[draft.llm_provider ?? cfg.llm_provider]) ?? []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">Change takes effect immediately for new requests.</p>
          </div>
        </div>
      </section>

      {/* Embeddings (read-only) */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-4">Embeddings (read-only)</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Provider</label>
            <input disabled value={cfg.embedding_provider} className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Model</label>
            <input disabled value={cfg.embedding_model} className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500" />
          </div>
        </div>
      </section>

      {/* RAG */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-4">RAG retrieval</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Top-K chunks retrieved: <strong>{draft.rag_top_k ?? cfg.rag_top_k}</strong>
            </label>
            <input
              type="range" min="1" max="20"
              value={draft.rag_top_k ?? cfg.rag_top_k}
              onChange={(e) => setDraft({ ...draft, rag_top_k: Number(e.target.value) })}
              className="w-full accent-indigo-600"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Min similarity score: <strong>{(draft.rag_min_score ?? cfg.rag_min_score).toFixed(2)}</strong>
            </label>
            <input
              type="range" min="0" max="1" step="0.01"
              value={draft.rag_min_score ?? cfg.rag_min_score}
              onChange={(e) => setDraft({ ...draft, rag_min_score: Number(e.target.value) })}
              className="w-full accent-indigo-600"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Context turns (read-only)</label>
              <input disabled value={cfg.rag_context_turns} className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Chunk tokens (read-only)</label>
              <input disabled value={cfg.chunk_tokens} className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-500" />
            </div>
          </div>
        </div>
      </section>

      {/* System prompt shortcut */}
      <section className="rounded-xl border border-gray-200 bg-indigo-50 border-indigo-200 shadow-sm p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-1">System prompt</h3>
        <p className="text-xs text-gray-500 mb-3">Use the <strong>Content</strong> tab to edit the system prompt, welcome message, and suggestion chips — all live without restart.</p>
      </section>

      {/* Voice & audio */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-4">Voice &amp; audio</h3>
        <div className="space-y-4">
          {/* TTS model */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">TTS model</label>
            <select
              value={draft.tts_model ?? cfg.tts_model}
              onChange={(e) => {
                const model = e.target.value;
                // If the currently-selected voice is not available in the new model, reset to first available
                const availableVoices = model === "gpt-4o-mini-tts" ? cfg.tts_voices_all : cfg.tts_voices_basic;
                const currentVoice = draft.tts_voice ?? cfg.tts_voice;
                const nextVoice = availableVoices.includes(currentVoice) ? currentVoice : availableVoices[0];
                setDraft({ ...draft, tts_model: model, tts_voice: nextVoice });
              }}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            >
              {cfg.tts_models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <p className="text-xs text-gray-400 mt-1">
              <code>gpt-4o-mini-tts</code> supports 13 voices and allows tone/accent instructions. <code>tts-1</code> is lower latency.
            </p>
          </div>
          {/* Voice */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">Default voice</label>
            <select
              value={draft.tts_voice ?? cfg.tts_voice}
              onChange={(e) => setDraft({ ...draft, tts_voice: e.target.value })}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            >
              {((draft.tts_model ?? cfg.tts_model) === "gpt-4o-mini-tts" ? cfg.tts_voices_all : cfg.tts_voices_basic).map(
                (v) => <option key={v} value={v}>{v}</option>,
              )}
            </select>
            <p className="text-xs text-gray-400 mt-1">
              Try voices at <a href="https://openai.fm/" target="_blank" rel="noopener noreferrer" className="underline">openai.fm</a>. Recommended: <code>marin</code> or <code>cedar</code> for highest quality.
            </p>
          </div>
          {/* STT model */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">STT model (transcription)</label>
            <select
              value={draft.stt_model ?? cfg.stt_model}
              onChange={(e) => setDraft({ ...draft, stt_model: e.target.value })}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
            >
              {cfg.stt_models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <p className="text-xs text-gray-400 mt-1">
              <code>gpt-4o-transcribe</code> is most accurate · <code>gpt-4o-mini-transcribe</code> is faster · <code>whisper-1</code> is the reliable classic.
            </p>
          </div>
        </div>
      </section>

      {/* Rate limits */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-4">Rate limiting</h3>
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={draft.rate_limit_enabled ?? cfg.rate_limit_enabled}
            onChange={(e) => setDraft({ ...draft, rate_limit_enabled: e.target.checked })}
            className="h-4 w-4 accent-indigo-600 rounded"
          />
          <span className="text-sm text-gray-700">Rate limiting enabled</span>
        </label>
        <div className="mt-4 space-y-2">
          {Object.entries(cfg.tier_limits).map(([tier, lims]) => (
            <div key={tier} className="flex items-center justify-between text-sm">
              <TierBadge tier={tier} />
              <span className="text-gray-500 text-xs">
                {lims.conversations_per_day < 0 ? "∞ conv/day" : `${lims.conversations_per_day} conv/day`}
                {" · "}
                {lims.turns_per_conversation < 0 ? "∞ turns" : `${lims.turns_per_conversation} turns`}
              </span>
            </div>
          ))}
          <p className="text-xs text-gray-400 pt-1">Per-tier limits are set in <code>session.py</code> — restart required to change.</p>
        </div>
      </section>

      {/* Save */}
      <div className="flex items-center gap-4">
        <button
          onClick={save}
          disabled={saving}
          className="px-5 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 text-sm font-medium"
        >
          {saving ? "Saving…" : "Apply changes"}
        </button>
        {msg && <span className={`text-sm ${msg.startsWith("Error") ? "text-red-600" : "text-emerald-600"}`}>{msg}</span>}
      </div>
    </div>
  );
}

// ── Eval tab ──────────────────────────────────────────────────────────────────

interface EvalRunSummary {
  name: string;
  run_at: string | null;
  label: string | null;
  model: string | null;
  provider: string | null;
  total: number;
  passed: number;
  failed: number;
  notes: string;
  error?: string;
}

interface EvalChunk {
  file: string;
  section: string;
  score: number;
  tier: string;
}

interface EvalCase {
  id: string;
  persona: string;
  tier: string;
  question: string;
  response: string;
  latency_ms: number;
  chunks: EvalChunk[];
  chunks_retrieved: number;
  error: string | null;
  keyword_hits: string[];
  keyword_misses: string[];
  forbidden_hits: string[];
  passed: boolean;
  notes?: string;
}

interface EvalRun {
  run_at: string;
  label: string | null;
  base_url: string;
  model: string | null;
  provider: string | null;
  notes?: string;
  cases: EvalCase[];
}

// Palette for runs (up to 6 selected at once)
const RUN_COLORS = [
  { ring: "ring-indigo-400",  bg: "bg-indigo-50",  header: "bg-indigo-600",  text: "text-indigo-700",  badge: "bg-indigo-100 text-indigo-700"  },
  { ring: "ring-violet-400",  bg: "bg-violet-50",  header: "bg-violet-600",  text: "text-violet-700",  badge: "bg-violet-100 text-violet-700"  },
  { ring: "ring-emerald-400", bg: "bg-emerald-50", header: "bg-emerald-600", text: "text-emerald-700", badge: "bg-emerald-100 text-emerald-700" },
  { ring: "ring-amber-400",   bg: "bg-amber-50",   header: "bg-amber-600",   text: "text-amber-700",   badge: "bg-amber-100 text-amber-700"   },
  { ring: "ring-rose-400",    bg: "bg-rose-50",    header: "bg-rose-600",    text: "text-rose-700",    badge: "bg-rose-100 text-rose-700"    },
  { ring: "ring-cyan-400",    bg: "bg-cyan-50",    header: "bg-cyan-600",    text: "text-cyan-700",    badge: "bg-cyan-100 text-cyan-700"    },
];

function EvalTab({ token }: { token: string }) {
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  // Multi-select: ordered list of selected run names (order = column order)
  const [selected, setSelected] = useState<string[]>([]);
  // Loaded run data keyed by filename
  const [runCache, setRunCache] = useState<Record<string, EvalRun>>({});
  const [expandedCase, setExpandedCase] = useState<string | null>(null);
  // Notes state keyed by run name
  const [runNotes, setRunNotes] = useState<Record<string, string>>({});
  const [caseNotes, setCaseNotes] = useState<Record<string, Record<string, string>>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  // Whether to show only failing cases across selected runs
  const [failuresOnly, setFailuresOnly] = useState(false);

  const loadRuns = useCallback(async () => {
    const res = await fetch("/api/admin/eval/runs", { headers: { "X-Access-Token": token } });
    if (res.ok) setRuns((await res.json()).runs);
  }, [token]);

  const loadRun = useCallback(async (name: string) => {
    if (runCache[name]) return;
    const res = await fetch(`/api/admin/eval/runs/${encodeURIComponent(name)}`, {
      headers: { "X-Access-Token": token },
    });
    if (!res.ok) return;
    const d: EvalRun = await res.json();
    setRunCache((prev) => ({ ...prev, [name]: d }));
    setRunNotes((prev) => ({ ...prev, [name]: d.notes ?? "" }));
    const cn: Record<string, string> = {};
    for (const c of d.cases) if (c.notes) cn[c.id] = c.notes;
    setCaseNotes((prev) => ({ ...prev, [name]: cn }));
  }, [token, runCache]);

  useEffect(() => { void loadRuns(); }, [loadRuns]);

  // Load data for each selected run
  useEffect(() => {
    for (const name of selected) void loadRun(name);
  }, [selected, loadRun]);

  const toggleSelect = (name: string) => {
    setSelected((prev) =>
      prev.includes(name)
        ? prev.filter((n) => n !== name)
        : prev.length < 6 ? [...prev, name] : prev
    );
  };

  const saveNotes = async (runName: string) => {
    setSaving(runName);
    const res = await fetch(`/api/admin/eval/runs/${encodeURIComponent(runName)}`, {
      method: "PATCH",
      headers: { "X-Access-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify({ notes: runNotes[runName] ?? "", case_notes: caseNotes[runName] ?? {} }),
    });
    setSaving(null);
    if (res.ok) {
      setSavedMsg("Saved ✓");
      setTimeout(() => setSavedMsg(null), 2500);
      setRuns((prev) => prev.map((r) => r.name === runName ? { ...r, notes: runNotes[runName] ?? "" } : r));
    }
  };

  const passRate = (r: EvalRunSummary) => r.total > 0 ? `${r.passed}/${r.total}` : "—";
  const fmtMs = (ms: number) => ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
  const shortLabel = (name: string, r?: EvalRunSummary | null) =>
    (r?.label ?? name.replace("golden_results_", "").replace(".json", "")).slice(0, 20);

  // Loaded runs in column order
  const loadedRuns = selected.map((n) => runCache[n]).filter(Boolean) as EvalRun[];
  const selectedMeta = selected.map((n) => runs.find((r) => r.name === n)).filter(Boolean) as EvalRunSummary[];

  // All case IDs across loaded runs
  const allCaseIds = loadedRuns.length > 0
    ? loadedRuns[0].cases.map((c) => c.id)
    : [];

  // In compare mode a case is "interesting" if pass/fail differs across columns
  const isDivergent = (caseId: string) => {
    const passes = loadedRuns.map((r) => r.cases.find((c) => c.id === caseId)?.passed ?? null);
    return passes.some((p) => p !== passes[0]);
  };

  const visibleIds = failuresOnly
    ? allCaseIds.filter((id) => loadedRuns.some((r) => !(r.cases.find((c) => c.id === id)?.passed ?? true)))
    : allCaseIds;

  return (
    <div className="flex gap-4 min-h-[70vh]">

      {/* ── Left sidebar: run list with checkboxes ── */}
      <div className="w-56 shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Test runs</h3>
          {selected.length > 0 && (
            <button onClick={() => setSelected([])} className="text-[10px] text-gray-400 hover:text-gray-600">
              Clear
            </button>
          )}
        </div>
        {selected.length === 0 && (
          <p className="text-[10px] text-gray-400 mb-3">Select one or more runs to compare.</p>
        )}
        {selected.length >= 6 && (
          <p className="text-[10px] text-amber-500 mb-2">Max 6 runs selected.</p>
        )}
        <div className="space-y-1.5">
          {runs.length === 0 && (
            <p className="text-xs text-gray-400">No runs found.<br />Run <code className="text-[10px]">make test-golden</code> first.</p>
          )}
          {runs.map((r) => {
            const selIdx = selected.indexOf(r.name);
            const isSelected = selIdx !== -1;
            const color = isSelected ? RUN_COLORS[selIdx] : null;
            return (
              <div
                key={r.name}
                onClick={() => toggleSelect(r.name)}
                className={`rounded-xl border p-2.5 cursor-pointer transition-all select-none ${
                  isSelected
                    ? `${color!.bg} ${color!.ring} ring-2 border-transparent`
                    : "border-gray-200 bg-white hover:bg-gray-50"
                }`}
              >
                {r.error ? (
                  <span className="text-xs text-red-500">unreadable</span>
                ) : (
                  <>
                    <div className="flex items-center gap-1.5 mb-0.5">
                      {isSelected && (
                        <span className={`text-[10px] font-bold rounded px-1 ${color!.badge}`}>
                          {selIdx + 1}
                        </span>
                      )}
                      <span className="text-xs font-semibold text-gray-800 truncate flex-1">
                        {shortLabel(r.name, r)}
                      </span>
                      <span className={`text-[10px] font-bold ${r.failed === 0 ? "text-emerald-600" : "text-red-500"}`}>
                        {passRate(r)}
                      </span>
                    </div>
                    <div className="text-[10px] text-gray-400 truncate">{r.provider}/{r.model}</div>
                    <div className="text-[10px] text-gray-400">
                      {r.run_at ? new Date(r.run_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}
                    </div>
                    {r.notes && <div className="mt-0.5 text-[10px] text-indigo-500 truncate">{r.notes}</div>}
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Main area ── */}
      <div className="flex-1 min-w-0">
        {selected.length === 0 ? (
          <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
            Select runs on the left to view or compare them
          </div>
        ) : loadedRuns.length < selected.length ? (
          <div className="flex items-center justify-center h-48 text-gray-400 text-sm">Loading…</div>
        ) : (
          <div className="space-y-4">

            {/* ── Score summary bar ── */}
            <div className="flex flex-wrap gap-3">
              {selectedMeta.map((r, i) => {
                const color = RUN_COLORS[i];
                return (
                  <div key={r.name} className={`rounded-xl border-2 ${color.ring} ${color.bg} px-4 py-3 flex items-center gap-3`}>
                    <span className={`text-xs font-bold rounded px-1.5 py-0.5 ${color.badge}`}>{i + 1}</span>
                    <div>
                      <div className="text-sm font-semibold text-gray-900">{shortLabel(r.name, r)}</div>
                      <div className="text-[10px] text-gray-500">{r.provider}/{r.model}</div>
                    </div>
                    <div className={`text-lg font-bold ml-2 ${r.failed === 0 ? "text-emerald-600" : "text-red-500"}`}>
                      {passRate(r)}
                    </div>
                    <div className="text-[10px] text-gray-400">
                      avg {fmtMs(Math.round((runCache[r.name]?.cases ?? []).reduce((s, c) => s + c.latency_ms, 0) / Math.max(runCache[r.name]?.cases.length ?? 1, 1)))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* ── Controls ── */}
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={failuresOnly}
                  onChange={(e) => setFailuresOnly(e.target.checked)}
                  className="accent-indigo-600"
                />
                Show only failing / divergent cases
              </label>
              {savedMsg && <span className="text-xs text-emerald-600 ml-auto">{savedMsg}</span>}
            </div>

            {/* ── Run notes (one per selected run, collapsible) ── */}
            {selected.length === 1 && (
              <div className="rounded-xl border border-gray-200 bg-white shadow-sm p-4">
                <div className="text-xs font-semibold text-gray-600 mb-2">Run note</div>
                <div className="flex gap-2">
                  <textarea
                    rows={2}
                    value={runNotes[selected[0]] ?? ""}
                    onChange={(e) => setRunNotes((prev) => ({ ...prev, [selected[0]]: e.target.value }))}
                    placeholder="Notes about this run…"
                    className="flex-1 text-xs rounded-lg border border-gray-200 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-400 resize-none"
                  />
                  <button
                    onClick={() => void saveNotes(selected[0])}
                    disabled={saving === selected[0]}
                    className="text-xs bg-indigo-600 text-white px-3 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                  >Save</button>
                </div>
              </div>
            )}

            {/* ── Case comparison table ── */}
            {visibleIds.length === 0 ? (
              <div className="text-center text-gray-400 text-sm py-8">No failing cases — all pass! 🎉</div>
            ) : (
              <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-x-auto">
                <table className="w-full text-sm min-w-[600px]">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr className="text-left text-xs text-gray-400 uppercase tracking-wider">
                      <th className="px-3 py-2.5 w-20 sticky left-0 bg-gray-50">ID</th>
                      <th className="px-3 py-2.5">Question</th>
                      {selectedMeta.map((r, i) => (
                        <th key={r.name} className={`px-3 py-2.5 w-24 text-center ${RUN_COLORS[i].text}`}>
                          <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold ${RUN_COLORS[i].badge}`}>{i + 1}</span>
                          {" "}{shortLabel(r.name, r)}
                        </th>
                      ))}
                      <th className="px-3 py-2.5 w-5" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {visibleIds.map((caseId) => {
                      const cases = loadedRuns.map((r) => r.cases.find((c) => c.id === caseId) ?? null);
                      const anyCase = cases.find(Boolean);
                      const isOpen = expandedCase === caseId;
                      const divergent = isDivergent(caseId);

                      return (
                        <>
                          <tr
                            key={caseId}
                            onClick={() => setExpandedCase(isOpen ? null : caseId)}
                            className={`cursor-pointer hover:bg-gray-50 ${divergent ? "bg-amber-50/30" : ""}`}
                          >
                            <td className="px-3 py-2 font-mono text-xs text-gray-500 sticky left-0 bg-inherit">{caseId}</td>
                            <td className="px-3 py-2 text-xs text-gray-700 max-w-[220px]">
                              <div className="truncate">{anyCase?.question}</div>
                              {divergent && <span className="text-[10px] text-amber-600">divergent</span>}
                            </td>
                            {cases.map((c, i) => (
                              <td key={i} className="px-3 py-2 text-center">
                                {c == null ? (
                                  <span className="text-gray-300 text-xs">—</span>
                                ) : c.passed ? (
                                  <span className="text-emerald-600 text-sm font-bold">✓</span>
                                ) : (
                                  <div>
                                    <span className="text-red-500 text-sm font-bold">✗</span>
                                    <div className="flex flex-col gap-0.5 mt-0.5">
                                      {c.keyword_misses.map((k) => (
                                        <span key={k} className="text-[9px] bg-red-100 text-red-600 px-1 rounded leading-tight">-{k}</span>
                                      ))}
                                      {c.forbidden_hits.map((k) => (
                                        <span key={k} className="text-[9px] bg-orange-100 text-orange-600 px-1 rounded leading-tight">!{k}</span>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </td>
                            ))}
                            <td className="px-3 py-2 text-gray-400 text-xs">{isOpen ? "▲" : "▼"}</td>
                          </tr>

                          {isOpen && (
                            <tr key={`${caseId}-exp`}>
                              <td colSpan={3 + loadedRuns.length} className="px-0 py-0 bg-gray-50">
                                <div className="p-3 space-y-3">
                                  {/* Response columns side by side */}
                                  <div
                                    className="grid gap-3"
                                    style={{ gridTemplateColumns: `repeat(${loadedRuns.length}, minmax(0, 1fr))` }}
                                  >
                                    {cases.map((c, i) => {
                                      const color = RUN_COLORS[i];
                                      const meta = selectedMeta[i];
                                      return (
                                        <div key={i} className={`rounded-lg border-2 ${color.ring} p-3`}>
                                          <div className={`text-[10px] font-bold uppercase tracking-wider mb-1.5 ${color.text}`}>
                                            {shortLabel(meta.name, meta)} · {meta.provider}/{meta.model}
                                          </div>
                                          {c == null ? (
                                            <div className="text-xs text-gray-400 italic">Not in this run</div>
                                          ) : c.error ? (
                                            <div className="text-xs text-red-600">{c.error}</div>
                                          ) : (
                                            <>
                                              <div className="text-xs text-gray-700 bg-white rounded border border-gray-100 p-2 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
                                                {c.response}
                                              </div>
                                              <div className="flex items-center gap-3 mt-1.5 text-[10px] text-gray-400">
                                                <span>{fmtMs(c.latency_ms)}</span>
                                                <span>{c.chunks_retrieved} chunks</span>
                                                {c.chunks.slice(0, 3).map((ch, ci) => (
                                                  <span key={ci} className="font-mono">{ch.score.toFixed(2)} {ch.file}</span>
                                                ))}
                                              </div>
                                            </>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>

                                  {/* Per-case note (applies to the first selected run for this case) */}
                                  {selected.length === 1 && (
                                    <div className="flex items-start gap-2 pt-1">
                                      <textarea
                                        rows={2}
                                        value={(caseNotes[selected[0]] ?? {})[caseId] ?? ""}
                                        onChange={(e) => setCaseNotes((prev) => ({
                                          ...prev,
                                          [selected[0]]: { ...(prev[selected[0]] ?? {}), [caseId]: e.target.value },
                                        }))}
                                        placeholder={`Note for ${caseId}…`}
                                        className="flex-1 text-xs rounded-lg border border-gray-200 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-400 resize-none"
                                      />
                                      <button
                                        onClick={() => void saveNotes(selected[0])}
                                        disabled={saving === selected[0]}
                                        className="text-xs bg-indigo-600 text-white px-3 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                                      >Save</button>
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Sessions tab ──────────────────────────────────────────────────────────────

function SessionsTab({ token }: { token: string }) {
  const [data, setData] = useState<{ sessions: Session[] } | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    const res = await fetch("/api/admin/sessions", { headers: { "X-Access-Token": token } });
    if (res.ok) setData(await res.json());
  }, [token]);

  useEffect(() => {
    load();
    intervalRef.current = setInterval(load, 10_000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [load]);

  if (!data) return <div className="text-gray-400 text-sm py-8 text-center">Loading…</div>;

  const active = data.sessions.filter((s) => !s.closed);
  const closed = data.sessions.filter((s) => s.closed);

  const SectionTable = ({ sessions }: { sessions: Session[] }) => (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr className="text-left text-xs text-gray-400 uppercase tracking-wider">
            <th className="px-4 py-2.5">Session ID</th>
            <th className="px-4 py-2.5">Tier</th>
            <th className="px-4 py-2.5">IP hash</th>
            <th className="px-4 py-2.5">Turns</th>
            <th className="px-4 py-2.5">Started</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {sessions.length === 0 && (
            <tr><td colSpan={5} className="px-4 py-4 text-center text-gray-400 text-xs">None</td></tr>
          )}
          {sessions.map((s) => (
            <tr key={s.session_id} className="hover:bg-gray-50">
              <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{s.session_id.slice(0, 12)}…</td>
              <td className="px-4 py-2.5"><TierBadge tier={s.tier} /></td>
              <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{s.ip_hash}</td>
              <td className="px-4 py-2.5 text-gray-700">{s.turns}</td>
              <td className="px-4 py-2.5 text-gray-500 text-xs">{fmtAgo(s.started_ago_s)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-3">
        <StatCard label="Active sessions" value={active.length} />
        <StatCard label="Closed sessions" value={closed.length} />
        <StatCard label="Total (since restart)" value={data.sessions.length} />
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">Active</h3>
        <SectionTable sessions={active} />
      </div>
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">Closed</h3>
        <SectionTable sessions={closed} />
      </div>
      <p className="text-xs text-gray-400">Auto-refreshes every 10 s. Sessions reset on container restart.</p>
    </div>
  );
}

// ── Roles & Access tab ────────────────────────────────────────────────────────

interface RoleDef {
  name: string;
  description: string;
  token_count: number;
  builtin: boolean;
}

interface TokenEntry {
  token: string;
  token_raw: string;
  roles: string[];
  tier: string;
  label: string;
  is_empty: boolean;
}

function RolesTab({ token }: { token: string }) {
  const [roles, setRoles] = useState<RoleDef[]>([]);
  const [tokens, setTokens] = useState<TokenEntry[]>([]);
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDesc, setNewRoleDesc] = useState("");
  const [showNewRole, setShowNewRole] = useState(false);
  const [newTokenLabel, setNewTokenLabel] = useState("");
  const [newTokenRoles, setNewTokenRoles] = useState<string[]>(["public"]);
  const [showNewToken, setShowNewToken] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [newlyCreatedToken, setNewlyCreatedToken] = useState<string | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [r, t] = await Promise.all([
      fetch("/api/admin/roles", { headers: { "X-Access-Token": token } }),
      fetch("/api/admin/tokens", { headers: { "X-Access-Token": token } }),
    ]);
    if (r.ok) setRoles((await r.json()).roles);
    if (t.ok) setTokens((await t.json()).tokens);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const createRole = async () => {
    if (!newRoleName.trim()) return;
    const res = await fetch("/api/admin/roles", {
      method: "POST",
      headers: { "X-Access-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify({ name: newRoleName.trim(), description: newRoleDesc.trim() }),
    });
    if (res.ok) {
      setShowNewRole(false); setNewRoleName(""); setNewRoleDesc(""); load();
    } else {
      const e = await res.json().catch(() => ({}));
      setMsg(`Error: ${e.detail ?? "unknown"}`);
    }
  };

  const deleteRole = async (name: string) => {
    const res = await fetch(`/api/admin/roles/${name}`, {
      method: "DELETE", headers: { "X-Access-Token": token },
    });
    if (res.ok) load();
    else setMsg("Failed to delete role");
  };

  const createToken = async () => {
    if (!newTokenLabel.trim() || newTokenRoles.length === 0) return;
    const res = await fetch("/api/admin/tokens", {
      method: "POST",
      headers: { "X-Access-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify({ label: newTokenLabel.trim(), roles: newTokenRoles }),
    });
    if (res.ok) {
      const data = await res.json();
      setNewlyCreatedToken(data.token);
      setShowNewToken(false); setNewTokenLabel(""); setNewTokenRoles(["public"]);
      load();
    } else {
      const e = await res.json().catch(() => ({}));
      setMsg(`Error: ${e.detail ?? "unknown"}`);
    }
  };

  const revokeToken = async (tokenKey: string) => {
    const res = await fetch(`/api/admin/tokens/${encodeURIComponent(tokenKey)}`, {
      method: "DELETE", headers: { "X-Access-Token": token },
    });
    setConfirmRevoke(null);
    if (res.ok) load();
    else {
      const e = await res.json().catch(() => ({}));
      setMsg(`Error: ${e.detail ?? "unknown"}`);
    }
  };

  const copyUrl = (tok: string) => {
    const url = `${window.location.origin}/?t=${tok}`;
    navigator.clipboard.writeText(url);
    setMsg(`Copied URL for token "${tok}"`);
    setTimeout(() => setMsg(null), 3000);
  };

  return (
    <div className="space-y-8">
      {msg && (
        <div className={`rounded-lg px-4 py-2.5 text-sm ${msg.startsWith("Error") ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`}>
          {msg}
        </div>
      )}
      {newlyCreatedToken && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <div className="font-medium text-emerald-800 mb-1">Token created</div>
          <p className="text-xs text-emerald-700 mb-2">Save this now — it won't be shown again.</p>
          <code className="block bg-white border border-emerald-200 rounded px-3 py-2 text-sm font-mono text-emerald-900 mb-2">
            {newlyCreatedToken}
          </code>
          <div className="flex gap-2">
            <button onClick={() => { navigator.clipboard.writeText(newlyCreatedToken); setMsg("Token copied!"); }} className="text-xs bg-emerald-600 text-white px-3 py-1.5 rounded hover:bg-emerald-700">Copy token</button>
            <button onClick={() => copyUrl(newlyCreatedToken)} className="text-xs border border-emerald-300 text-emerald-700 px-3 py-1.5 rounded hover:bg-emerald-100">Copy share URL</button>
            <button onClick={() => setNewlyCreatedToken(null)} className="text-xs text-gray-500 px-2 py-1.5 rounded hover:bg-gray-100 ml-auto">Dismiss</button>
          </div>
        </div>
      )}

      {/* Roles */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-700">Roles</h3>
          <button onClick={() => setShowNewRole(true)} className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">+ Add role</button>
        </div>
        {showNewRole && (
          <div className="mb-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4">
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Role name (slug)</label>
                <input value={newRoleName} onChange={(e) => setNewRoleName(e.target.value)}
                  placeholder="e.g. investor"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Description</label>
                <input value={newRoleDesc} onChange={(e) => setNewRoleDesc(e.target.value)}
                  placeholder="e.g. Potential investors"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={createRole} className="text-sm bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700">Create</button>
              <button onClick={() => setShowNewRole(false)} className="text-sm text-gray-500 px-4 py-2 rounded-lg hover:bg-gray-100">Cancel</button>
            </div>
          </div>
        )}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr className="text-left text-xs text-gray-400 uppercase tracking-wider">
                <th className="px-4 py-2.5">Role</th>
                <th className="px-4 py-2.5">Description</th>
                <th className="px-4 py-2.5">Tokens</th>
                <th className="px-4 py-2.5 w-16" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {roles.map((r) => (
                <tr key={r.name} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <TierBadge tier={r.name} />
                      {r.builtin && <span className="text-[10px] text-gray-400">built-in</span>}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-gray-600">{r.description || "—"}</td>
                  <td className="px-4 py-2.5 text-gray-700">{r.token_count}</td>
                  <td className="px-4 py-2.5">
                    {!r.builtin && (
                      <button onClick={() => deleteRole(r.name)} className="text-red-400 hover:text-red-600 text-xs">Delete</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Tokens */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-700">Access tokens</h3>
          <button onClick={() => setShowNewToken(true)} className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">+ Generate token</button>
        </div>
        {showNewToken && (
          <div className="mb-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4">
            <div className="mb-3">
              <label className="block text-xs text-gray-500 mb-1">Label</label>
              <input value={newTokenLabel} onChange={(e) => setNewTokenLabel(e.target.value)}
                placeholder="e.g. Recruiter — ACME Corp"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm" />
            </div>
            <div className="mb-3">
              <label className="block text-xs text-gray-500 mb-2">Grant roles</label>
              <div className="flex flex-wrap gap-2">
                {roles.map((r) => (
                  <label key={r.name} className="flex items-center gap-1.5 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={newTokenRoles.includes(r.name)}
                      onChange={(e) => setNewTokenRoles(e.target.checked ? [...newTokenRoles, r.name] : newTokenRoles.filter((x) => x !== r.name))}
                      className="accent-indigo-600"
                    />
                    {r.name}
                  </label>
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={createToken} className="text-sm bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700">Generate</button>
              <button onClick={() => setShowNewToken(false)} className="text-sm text-gray-500 px-4 py-2 rounded-lg hover:bg-gray-100">Cancel</button>
            </div>
          </div>
        )}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr className="text-left text-xs text-gray-400 uppercase tracking-wider">
                <th className="px-4 py-2.5">Label</th>
                <th className="px-4 py-2.5">Roles</th>
                <th className="px-4 py-2.5">Token</th>
                <th className="px-4 py-2.5 w-24" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {tokens.map((t) => (
                <tr key={t.token} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5 text-gray-700">{t.label || <span className="text-gray-400 italic">no label</span>}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {t.roles.map((r) => <TierBadge key={r} tier={r} />)}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-400">
                    {t.is_empty ? <span className="italic">anonymous</span> : `${t.token.slice(0, 12)}…`}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex gap-2">
                      {!t.is_empty && (
                        <>
                          <button onClick={() => copyUrl(t.token_raw)} className="text-xs text-indigo-600 hover:text-indigo-800">Copy URL</button>
                          <button onClick={() => setConfirmRevoke(t.token_raw)} className="text-xs text-red-400 hover:text-red-600">Revoke</button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {confirmRevoke && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="font-semibold text-gray-900 mb-2">Revoke token?</h3>
            <p className="text-sm text-gray-500 font-mono mb-4">{confirmRevoke}</p>
            <p className="text-xs text-gray-400 mb-4">Anyone using this token will immediately lose access.</p>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setConfirmRevoke(null)} className="px-4 py-2 text-sm rounded-lg border border-gray-200 hover:bg-gray-50">Cancel</button>
              <button onClick={() => revokeToken(confirmRevoke)} className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700">Revoke</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Root Admin component ──────────────────────────────────────────────────────

interface AdminProps {
  token: string;
  onExit: () => void;
}

function AdminLogin({ onLogin, onExit, error: initialError }: { onLogin: (t: string) => void; onExit: () => void; error?: string }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [loading, setLoading] = useState(false);

  const attempt = async () => {
    const t = value.trim();
    if (!t) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/admin/stats", { headers: { "X-Access-Token": t } });
      if (res.ok) {
        onLogin(t);
      } else if (res.status === 403) {
        setError("Invalid token — personal tier required.");
      } else {
        setError("Server error, please try again.");
      }
    } catch {
      setError("Could not reach server.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-lg border border-gray-200 overflow-hidden">
        <div className="bg-indigo-600 px-6 py-5 flex items-center gap-3">
          <div className="h-10 w-10 rounded-full overflow-hidden bg-white/20">
            <img src="/avatar_sebastiaan.png" alt="" className="h-full w-full object-cover" />
          </div>
          <div>
            <div className="text-white font-semibold">Digital Twin — Admin</div>
            <div className="text-indigo-200 text-xs">Personal tier access required</div>
          </div>
        </div>
        <div className="px-6 py-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Access token</label>
            <input
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void attempt(); }}
              placeholder="pers-…"
              autoFocus
              className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            onClick={() => void attempt()}
            disabled={loading || !value.trim()}
            className="w-full rounded-lg bg-indigo-600 text-white py-2.5 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Checking…" : "Sign in"}
          </button>
          <button onClick={onExit} className="w-full text-center text-sm text-gray-400 hover:text-gray-600">
            ← Back to chat
          </button>
        </div>
      </div>
    </div>
  );
}

export function Admin({ token: initialToken, onExit }: AdminProps) {
  const [token, setToken] = useState(initialToken);
  const [tab, setTab] = useState<Tab>("overview");
  const [pendingKnowledgeNode, setPendingKnowledgeNode] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    setStats(null);
    setStatsError(null);
    (async () => {
      const res = await fetch("/api/admin/stats", { headers: { "X-Access-Token": token } });
      if (res.status === 403) {
        setStatsError("Access denied — personal-tier token required.");
      } else if (res.ok) {
        setStats(await res.json());
      } else {
        setStatsError("Failed to load stats.");
      }
    })();
  }, [token]);

  const handleLogin = (t: string) => {
    setToken(t);
    setStatsError(null);
    window.history.replaceState({}, "", `?page=admin&t=${t}`);
  };

  // Show login form if no token or if auth failed
  if (!token || statsError) {
    return (
      <AdminLogin
        onLogin={handleLogin}
        onExit={onExit}
        error={statsError ?? undefined}
      />
    );
  }

  const TABS: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "logs", label: "Logs" },
    { id: "content", label: "Content" },
    { id: "knowledge", label: "Knowledge" },
    { id: "graph", label: "Graph" },
    { id: "config", label: "Config" },
    { id: "roles", label: "Roles & Access" },
    { id: "sessions", label: "Sessions" },
    { id: "translations", label: "NL Translations" },
    { id: "eval", label: "Eval" },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="h-7 w-7 rounded-full overflow-hidden bg-gray-100">
            <img src="/avatar_sebastiaan.png" alt="" className="h-full w-full object-cover" />
          </div>
          <span className="font-semibold text-gray-900 text-sm">Admin — Digital Twin</span>
          <span className="text-xs text-gray-400 hidden sm:inline">personal tier</span>
        </div>
        <button onClick={onExit} className="text-sm text-indigo-600 hover:text-indigo-800 font-medium">
          ← Back to chat
        </button>
      </header>

      {/* Tab nav */}
      <nav className="bg-white border-b border-gray-200 px-6 flex gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? "border-indigo-600 text-indigo-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* Content — full-height for graph/knowledge/memory, max-width for others */}
      {(tab === "knowledge" || tab === "graph") ? (
        <div className="flex-1 overflow-hidden" style={{ height: "calc(100vh - 113px)" }}>
          {tab === "knowledge" && (
              <KnowledgeTab
                token={token}
                initialNodeId={pendingKnowledgeNode}
                onNavigated={() => setPendingKnowledgeNode(null)}
              />
          )}
          {tab === "graph" && (
            <GraphTab
              token={token}
              onNavigateToNode={(id) => {
                setPendingKnowledgeNode(id);
                setTab("knowledge");
              }}
            />
          )}
        </div>
      ) : (
        <main className="max-w-6xl mx-auto px-6 py-6">
          {tab === "overview" && (
            stats
              ? <OverviewTab stats={stats} />
              : <div className="text-gray-400 text-sm py-12 text-center">Loading stats…</div>
          )}
          {tab === "logs" && <LogsTab token={token} />}
          {tab === "content" && <ContentTab token={token} />}
          {tab === "config" && <ConfigTab token={token} />}
          {tab === "roles" && <RolesTab token={token} />}
          {tab === "sessions" && <SessionsTab token={token} />}
          {tab === "translations" && <TranslationsTab token={token} />}
          {tab === "eval" && <EvalTab token={token} />}
        </main>
      )}
    </div>
  );
}
