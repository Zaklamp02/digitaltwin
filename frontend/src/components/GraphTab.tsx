import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// ── types ─────────────────────────────────────────────────────────────────────

interface GraphNode {
  id: string;
  type: string;
  title: string;
  roles: string[];
  edge_count: number;
  tier: number;
  has_document?: boolean;
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
}

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface Pos {
  x: number;
  y: number;
  r: number;
  opacity: number;
}

interface NodeDetailEdge {
  id: string;
  direction: "incoming" | "outgoing";
  other_title: string;
  other_type: string;
  type: string;
  label: string;
  source_id: string;
  target_id: string;
}

interface NodeDetailLight {
  body: string;
  edges: NodeDetailEdge[];
}

// ── constants ─────────────────────────────────────────────────────────────────

const TYPE_FILL: Record<string, string> = {
  person:    "#6366f1",
  job:       "#f59e0b",
  project:   "#10b981",
  skill:     "#3b82f6",
  education: "#8b5cf6",
  community: "#06b6d4",
  document:  "#9ca3af",
  opinion:   "#f97316",
  personal:  "#ec4899",
  faq:       "#84cc16",
  system:    "#ef4444",
  notebook:  "#eab308",
};

const TYPE_ABBR: Record<string, string> = {
  person:    "👤",
  job:       "💼",
  project:   "🚀",
  skill:     "⚡",
  education: "🎓",
  community: "🌐",
  document:  "📄",
  opinion:   "💬",
  personal:  "♥",
  faq:       "❓",
  system:    "⚙",
  hub:       "H",
  notebook:  "📓",
};

const EDGE_TYPES = [
  "worked_at", "built", "knows", "studied_at", "member_of",
  "relates_to", "used_in", "describes", "authored",
  "has", "includes", "uses",
  "nb_page",   // notebook → node (this node is a page in the notebook)
];

// Edges that represent notebook containment (notebook → page)
// All edge types that represent containment (parent → child hierarchy)
const NB_CONTAINMENT_TYPES = new Set(["nb_page", "includes", "has", "member_of", "studied_at"]);

const NODE_R_BASE = 14;
const TIER_RADII  = [0, 120, 220, 330, 430];
const SIM_TICKS   = 500;
const REPULSION   = 2200;
const SPRING_K    = 0.022;
const TARGET_DIST = 110;
const RADIAL_K    = 0.09;
const DAMPING     = 0.72;
const LERP        = 0.14;

// ── tier-based initial placement ─────────────────────────────────────────────

function initialPlacement(nodes: SimNode[], w: number, h: number): void {
  const cx = w / 2, cy = h / 2;
  const byTier = new Map<number, SimNode[]>();
  for (const n of nodes) {
    const t = n.tier ?? 3;
    if (!byTier.has(t)) byTier.set(t, []);
    byTier.get(t)!.push(n);
  }
  for (const [tier, group] of byTier) {
    const r = TIER_RADII[Math.min(tier, TIER_RADII.length - 1)];
    group.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / group.length - Math.PI / 2;
      n.x  = cx + r * Math.cos(angle) + (Math.random() - 0.5) * 12;
      n.y  = cy + r * Math.sin(angle) + (Math.random() - 0.5) * 12;
      n.vx = 0;
      n.vy = 0;
    });
  }
}

// ── force simulation ──────────────────────────────────────────────────────────

function runSimulation(
  nodes: SimNode[],
  edges: GraphEdge[],
  w: number,
  h: number,
  ticks: number,
): void {
  const cx = w / 2, cy = h / 2;
  const idx = new Map<string, number>(nodes.map((n, i) => [n.id, i]));

  for (let t = 0; t < ticks; t++) {
    const ax = new Float64Array(nodes.length);
    const ay = new Float64Array(nodes.length);

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const d2 = dx * dx + dy * dy + 1;
        const d  = Math.sqrt(d2);
        const f  = REPULSION / d2;
        ax[i] += f * dx / d; ay[i] += f * dy / d;
        ax[j] -= f * dx / d; ay[j] -= f * dy / d;
      }
    }

    for (const e of edges) {
      const si = idx.get(e.source);
      const ti = idx.get(e.target);
      if (si === undefined || ti === undefined) continue;
      const dx = nodes[ti].x - nodes[si].x;
      const dy = nodes[ti].y - nodes[si].y;
      const d  = Math.sqrt(dx * dx + dy * dy) || 1;
      const f  = SPRING_K * (d - TARGET_DIST);
      ax[si] += f * dx / d; ay[si] += f * dy / d;
      ax[ti] -= f * dx / d; ay[ti] -= f * dy / d;
    }

    for (let i = 0; i < nodes.length; i++) {
      const tgtR = TIER_RADII[Math.min(nodes[i].tier ?? 3, TIER_RADII.length - 1)];
      const dx   = nodes[i].x - cx;
      const dy   = nodes[i].y - cy;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const rDiff = dist - tgtR;
      ax[i] -= RADIAL_K * rDiff * (dx / dist);
      ay[i] -= RADIAL_K * rDiff * (dy / dist);
    }

    for (let i = 0; i < nodes.length; i++) {
      nodes[i].vx = (nodes[i].vx + ax[i]) * DAMPING;
      nodes[i].vy = (nodes[i].vy + ay[i]) * DAMPING;
      nodes[i].x  = Math.max(20, Math.min(w - 20, nodes[i].x + nodes[i].vx));
      nodes[i].y  = Math.max(20, Math.min(h - 20, nodes[i].y + nodes[i].vy));
    }
  }
}

// ── helpers ───────────────────────────────────────────────────────────────────

function buildSimTargets(nodes: SimNode[]): Map<string, Pos> {
  const m = new Map<string, Pos>();
  for (const n of nodes) {
    m.set(n.id, { x: n.x, y: n.y, r: NODE_R_BASE + Math.min(n.edge_count, 8), opacity: 1 });
  }
  return m;
}

function computeFocusTargets(
  selectedId: string,
  nodes: SimNode[],
  edges: GraphEdge[],
  w: number,
  h: number,
): Map<string, Pos> {
  const cx = w / 2;
  const cy = h / 2;
  const maxR = Math.min(w * 0.86, h * 0.80) / 2;

  const hop = new Map<string, number>([[selectedId, 0]]);
  let frontier = [selectedId];
  for (let depth = 1; depth <= 2; depth++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const e of edges) {
        const nbr = e.source === id ? e.target : e.target === id ? e.source : null;
        if (nbr && !hop.has(nbr)) { hop.set(nbr, depth); next.push(nbr); }
      }
    }
    frontier = next;
  }

  const h1 = [...hop.entries()].filter(([, d]) => d === 1).map(([id]) => id);
  const h2 = [...hop.entries()].filter(([, d]) => d === 2).map(([id]) => id);

  const result = new Map<string, Pos>();
  result.set(selectedId, { x: cx, y: cy, r: 30, opacity: 1 });

  const r1 = maxR * 0.44;
  h1.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / Math.max(h1.length, 1) - Math.PI / 2;
    result.set(id, { x: cx + r1 * Math.cos(angle), y: cy + r1 * Math.sin(angle), r: 20, opacity: 1 });
  });

  const r2 = maxR * 0.90;
  h2.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / Math.max(h2.length, 1) - Math.PI / 2;
    result.set(id, { x: cx + r2 * Math.cos(angle), y: cy + r2 * Math.sin(angle), r: 14, opacity: 0.85 });
  });

  for (const n of nodes) {
    if (!result.has(n.id)) {
      result.set(n.id, { x: n.x, y: n.y, r: 9, opacity: 0.12 });
    }
  }
  return result;
}

let _graphToken = "";

async function apiFetch(path: string, opts?: RequestInit) {
  const res = await fetch(`/api/admin${path}`, {
    ...opts,
    headers: {
      "X-Access-Token": _graphToken,
      "Content-Type": "application/json",
      ...(opts?.headers ?? {}),
    },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// ── AddEdgeModal ──────────────────────────────────────────────────────────────

function AddEdgeModal({
  nodeId,
  allNodes,
  onClose,
  onCreated,
}: {
  nodeId: string;
  allNodes: SimNode[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [edgeType, setEdgeType] = useState(EDGE_TYPES[0]);
  const [targetId, setTargetId] = useState("");
  const [targetSearch, setTargetSearch] = useState("");
  const [showNodeList, setShowNodeList] = useState(false);
  const [label, setLabel] = useState("");
  const [roles, setRoles] = useState<string[]>(["public"]);
  const [direction, setDirection] = useState<"outgoing" | "incoming">("outgoing");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const candidates = allNodes.filter(n => n.id !== nodeId);
  const filtered = targetSearch.trim()
    ? candidates.filter(n =>
        n.title.toLowerCase().includes(targetSearch.toLowerCase()) ||
        n.id.toLowerCase().includes(targetSearch.toLowerCase())
      )
    : candidates;
  const selectedNode = candidates.find(n => n.id === targetId);

  const toggleRole = (r: string) =>
    setRoles(prev => prev.includes(r) ? prev.filter(x => x !== r) : [...prev, r]);

  async function submit() {
    if (!targetId) { setErr("Select a target node"); return; }
    setSaving(true); setErr("");
    try {
      await apiFetch("/edges", {
        method: "POST",
        body: JSON.stringify({
          source_id: direction === "outgoing" ? nodeId : targetId,
          target_id: direction === "outgoing" ? targetId : nodeId,
          type: edgeType,
          label,
          roles,
        }),
      });
      onCreated();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <h3 className="font-semibold text-gray-900 mb-4">Add relationship</h3>
        <div className="space-y-3">
          <div className="flex gap-2">
            <button
              className={`flex-1 py-1.5 rounded text-sm font-medium border ${direction === "outgoing" ? "bg-indigo-50 border-indigo-300 text-indigo-700" : "border-gray-200 text-gray-600"}`}
              onClick={() => setDirection("outgoing")}
            >This → other</button>
            <button
              className={`flex-1 py-1.5 rounded text-sm font-medium border ${direction === "incoming" ? "bg-indigo-50 border-indigo-300 text-indigo-700" : "border-gray-200 text-gray-600"}`}
              onClick={() => setDirection("incoming")}
            >Other → this</button>
          </div>

          <div className="relative">
            {selectedNode ? (
              <div className="flex items-center gap-2 border border-indigo-300 bg-indigo-50 rounded px-3 py-2">
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded text-white font-medium"
                  style={{ backgroundColor: TYPE_FILL[selectedNode.type] ?? "#9ca3af" }}
                >{selectedNode.type}</span>
                <span className="flex-1 text-sm font-medium text-gray-800 truncate">{selectedNode.title}</span>
                <button
                  onClick={() => { setTargetId(""); setTargetSearch(""); setShowNodeList(true); }}
                  className="text-gray-400 hover:text-gray-600 text-xs flex-shrink-0"
                >✕</button>
              </div>
            ) : (
              <input
                autoFocus
                className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
                placeholder="Search nodes to connect…"
                value={targetSearch}
                onChange={e => { setTargetSearch(e.target.value); setShowNodeList(true); }}
                onFocus={() => setShowNodeList(true)}
              />
            )}
            {showNodeList && !selectedNode && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-52 overflow-y-auto z-10">
                {filtered.length === 0 && <p className="text-xs text-gray-400 px-3 py-2 italic">No nodes match</p>}
                {filtered.slice(0, 40).map(n => (
                  <button
                    key={n.id}
                    onClick={() => { setTargetId(n.id); setShowNodeList(false); setTargetSearch(""); }}
                    className="w-full text-left px-3 py-2 hover:bg-indigo-50 flex items-center gap-2 border-b border-gray-100 last:border-0"
                  >
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded text-white font-medium flex-shrink-0"
                      style={{ backgroundColor: TYPE_FILL[n.type] ?? "#9ca3af" }}
                    >{n.type}</span>
                    <span className="flex-1 text-sm text-gray-800 truncate">{n.title}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <select
            className="w-full border border-gray-200 rounded px-3 py-2 text-sm"
            value={edgeType}
            onChange={e => setEdgeType(e.target.value)}
          >
            {EDGE_TYPES.map(t => <option key={t}>{t}</option>)}
          </select>

          <input
            className="w-full border border-gray-200 rounded px-3 py-2 text-sm"
            placeholder="Label (optional)"
            value={label}
            onChange={e => setLabel(e.target.value)}
          />

          <div className="flex gap-2 flex-wrap">
            {["public", "work", "friends", "personal"].map(r => (
              <label key={r} className="flex items-center gap-1 text-sm cursor-pointer">
                <input type="checkbox" checked={roles.includes(r)} onChange={() => toggleRole(r)} />
                {r}
              </label>
            ))}
          </div>

          {err && <p className="text-sm text-red-600">{err}</p>}
        </div>
        <div className="flex gap-2 mt-4">
          <button
            className="flex-1 bg-indigo-600 text-white py-2 rounded text-sm font-medium disabled:opacity-50"
            onClick={submit}
            disabled={saving}
          >{saving ? "Adding…" : "Add relationship"}</button>
          <button className="flex-1 border border-gray-200 py-2 rounded text-sm text-gray-600" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Memory chat sidebar ───────────────────────────────────────────────────────

interface MemoryChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolCalls?: { id: string; name: string; args: string }[];
  toolResults?: { name: string; result: unknown }[];
}

function ToolCallCard({ name, args, result }: { name: string; args: string; result?: unknown }) {
  const [expanded, setExpanded] = useState(false);
  let parsedArgs: unknown = {};
  try { parsedArgs = JSON.parse(args || "{}"); } catch { /* ignore */ }
  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-2 text-xs font-mono w-full">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left"
      >
        <span className="text-indigo-700 font-bold">{name}</span>
        <span className="text-indigo-400 truncate flex-1">
          {args.length > 80 ? args.slice(0, 79) + "…" : args}
        </span>
        <span className="text-indigo-400 flex-shrink-0">{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1.5">
          <pre className="bg-white rounded border border-indigo-100 p-2 overflow-x-auto text-[10px]">
            {JSON.stringify(parsedArgs, null, 2)}
          </pre>
          {result !== undefined && (
            <pre className="bg-emerald-50 rounded border border-emerald-200 p-2 overflow-x-auto text-[10px] text-emerald-800">
              {JSON.stringify(result, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

const MEMORY_CHIPS = [
  "List all nodes",
  "Show career and job nodes",
  "Find nodes with no edges (orphans)",
  "Summarise the personal nodes",
];

function MemoryChatSidebar({ token }: { token: string }) {
  const [messages, setMessages] = useState<MemoryChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [nodes, setNodes] = useState<{ id: string; title: string; type: string }[]>([]);
  const [showPicker, setShowPicker] = useState(false);
  const [pickerFilter, setPickerFilter] = useState("");

  useEffect(() => {
    fetch("/api/admin/nodes", { headers: { "X-Access-Token": token } })
      .then(r => (r.ok ? r.json() : null))
      .then(data => data && setNodes(data.nodes || []));
  }, [token]);

  const filteredNodes = nodes
    .filter(n =>
      pickerFilter
        ? n.title.toLowerCase().includes(pickerFilter.toLowerCase()) ||
          n.id.toLowerCase().includes(pickerFilter.toLowerCase())
        : true
    )
    .slice(0, 8);

  function handleInputChange(val: string) {
    setInput(val);
    const atIdx = val.lastIndexOf("@");
    if (atIdx >= 0 && val.slice(atIdx).length <= 40) {
      setShowPicker(true);
      setPickerFilter(val.slice(atIdx + 1));
    } else {
      setShowPicker(false);
    }
  }

  function selectNode(node: { id: string; title: string }) {
    const atIdx = input.lastIndexOf("@");
    setInput(input.slice(0, atIdx) + `@${node.id} `);
    setShowPicker(false);
  }

  async function sendMessage(text: string) {
    if (!text.trim() || loading) return;
    const userMsg: MemoryChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: text.trim(),
    };
    const history = messages.map(m => ({ role: m.role, content: m.text }));
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    const assistantId = crypto.randomUUID();
    const assistantMsg: MemoryChatMessage = {
      id: assistantId,
      role: "assistant",
      text: "",
      toolCalls: [],
      toolResults: [],
    };
    setMessages(prev => [...prev, assistantMsg]);

    try {
      const res = await fetch("/api/admin/memory-chat", {
        method: "POST",
        headers: { "X-Access-Token": token, "Content-Type": "application/json" },
        body: JSON.stringify({ message: text.trim(), history }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          if (!frame.startsWith("data:")) continue;
          const raw = frame.slice(5).replace(/^\s/, "").trim();
          if (!raw || raw === "[DONE]") continue;
          try {
            const ev = JSON.parse(raw);
            setMessages(prev =>
              prev.map(m => {
                if (m.id !== assistantId) return m;
                if (ev.type === "chunk" && ev.text) return { ...m, text: m.text + ev.text };
                if (ev.type === "tool_calls" && ev.calls) return { ...m, toolCalls: [...(m.toolCalls ?? []), ...ev.calls] };
                if (ev.type === "tool_result") return { ...m, toolResults: [...(m.toolResults ?? []), { name: ev.name, result: ev.result }] };
                if (ev.type === "error") return { ...m, text: m.text || `⚠ ${ev.text}` };
                return m;
              })
            );
          } catch { /* ignore parse errors */ }
        }
      }
    } catch (err) {
      setMessages(prev =>
        prev.map(m => m.id === assistantId ? { ...m, text: `⚠ ${String(err)}` } : m)
      );
    } finally {
      setLoading(false);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
    }
  }

  return (
    <div className="flex flex-col h-full border-l border-gray-200 bg-white w-80 flex-shrink-0">
      {/* Header */}
      <div className="px-3 py-2 border-b border-gray-100 flex items-center gap-2 flex-shrink-0">
        <span className="text-base">🧠</span>
        <span className="text-sm font-semibold text-gray-700">Memory Chat</span>
      </div>
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 min-h-0">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <p className="text-xs text-gray-500 font-semibold mb-1">Memory Management</p>
            <p className="text-xs text-gray-400 mb-4">
              Ask about or update graph nodes. Type @ to reference a node.
            </p>
            <div className="flex flex-col gap-1.5">
              {MEMORY_CHIPS.map(chip => (
                <button
                  key={chip}
                  onClick={() => sendMessage(chip)}
                  className="text-xs px-3 py-1.5 rounded-full border border-indigo-200 text-indigo-700 hover:bg-indigo-50 text-left"
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map(msg => (
          <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-full w-full space-y-1.5 flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
              {(msg.toolCalls ?? []).map((tc, i) => {
                const result = (msg.toolResults ?? []).find(r => r.name === tc.name);
                return <ToolCallCard key={i} name={tc.name} args={tc.args} result={result?.result} />;
              })}
              {(msg.text || (loading && msg.role === "assistant")) && (
                <div className={`rounded-xl px-3 py-2 text-xs whitespace-pre-wrap break-words ${
                  msg.role === "user"
                    ? "bg-indigo-600 text-white rounded-br-sm"
                    : "bg-gray-50 border border-gray-200 text-gray-800 rounded-bl-sm"
                }`}>
                  {msg.text || <span className="text-gray-400 italic">thinking…</span>}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      {/* Input */}
      <div className="border-t border-gray-200 bg-white p-2 relative flex-shrink-0">
        {showPicker && filteredNodes.length > 0 && (
          <div className="absolute bottom-full left-2 right-2 mb-1 bg-white rounded-xl border border-gray-200 shadow-lg max-h-48 overflow-y-auto z-20">
            {filteredNodes.map(n => (
              <button
                key={n.id}
                onClick={() => selectNode(n)}
                className="w-full text-left px-3 py-2 hover:bg-gray-50 text-xs flex items-center gap-2 border-b border-gray-100 last:border-0"
              >
                <span className="text-[10px] px-1 py-0.5 rounded bg-gray-100 text-gray-500 font-mono flex-shrink-0">{n.type}</span>
                <span className="text-gray-800 flex-1 truncate">{n.title}</span>
              </button>
            ))}
          </div>
        )}
        <div className="flex gap-1.5 items-end">
          <textarea
            value={input}
            onChange={e => handleInputChange(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
            }}
            placeholder="Ask about the graph… @ to pick a node"
            rows={2}
            className="flex-1 resize-none rounded-lg border border-gray-200 px-2 py-1.5 text-xs focus:outline-none focus:border-indigo-400"
            disabled={loading}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
            className="px-3 py-2 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-40 flex-shrink-0"
          >
            {loading ? "…" : "↑"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── component ─────────────────────────────────────────────────────────────────

export default function GraphTab({
  token,
  onNavigateToNode,
}: {
  token: string;
  onNavigateToNode?: (nodeId: string) => void;
}) {
  _graphToken = token;

  const svgRef       = useRef<SVGSVGElement>(null);
  const simRef       = useRef<SimNode[]>([]);
  const edgesRef     = useRef<GraphEdge[]>([]);
  const draggingRef  = useRef<{ id: string; ox: number; oy: number } | null>(null);
  const displayRef   = useRef<Map<string, Pos>>(new Map());
  const targetRef    = useRef<Map<string, Pos>>(new Map());
  const animRef      = useRef<number>(0);
  const transformRef = useRef({ x: 0, y: 0, scale: 1 });
  const panningRef   = useRef<{ startX: number; startY: number; initX: number; initY: number } | null>(null);

  const [, setTick]               = useState(0);
  const [selected, setSelected]   = useState<SimNode | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const [loading, setLoading]     = useState(true);
  const [err, setErr]             = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [dimensions, setDimensions] = useState({ w: 900, h: 600 });
  const [showMemoryChat, setShowMemoryChat] = useState(true);
  const [nodeDetail, setNodeDetail]         = useState<NodeDetailLight | null>(null);
  const [nodeDetailLoading, setNodeDetailLoading] = useState(false);
  const [showAddEdge, setShowAddEdge]       = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [nbDepths, setNbDepths]     = useState<Map<string, number>>(new Map());
  const [showOrphanPanel, setShowOrphanPanel] = useState(false);

  function toggleCollapse(nodeId: string) {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }

  // ── animation loop ─────────────────────────────────────────────────────────

  function startAnim() {
    cancelAnimationFrame(animRef.current);
    const step = () => {
      let moving = false;
      for (const [id, tgt] of targetRef.current) {
        const cur = displayRef.current.get(id) ?? { ...tgt };
        const nx  = cur.x + (tgt.x - cur.x) * LERP;
        const ny  = cur.y + (tgt.y - cur.y) * LERP;
        const nr  = cur.r + (tgt.r - cur.r) * LERP;
        const no  = cur.opacity + (tgt.opacity - cur.opacity) * LERP;
        if (Math.abs(nx - tgt.x) > 0.3 || Math.abs(ny - tgt.y) > 0.3) moving = true;
        displayRef.current.set(id, { x: nx, y: ny, r: nr, opacity: no });
      }
      setTick(t => t + 1);
      if (moving) animRef.current = requestAnimationFrame(step);
    };
    animRef.current = requestAnimationFrame(step);
  }

  // ── measure container ──────────────────────────────────────────────────────

  useEffect(() => {
    const obs = new ResizeObserver(entries => {
      for (const e of entries) {
        setDimensions({ w: e.contentRect.width, h: e.contentRect.height });
      }
    });
    if (svgRef.current?.parentElement) obs.observe(svgRef.current.parentElement);
    return () => obs.disconnect();
  }, []);

  // ── load graph data ────────────────────────────────────────────────────────

  function loadGraph() {
    setLoading(true);
    setErr("");
    setSelected(null);
    setNodeDetail(null);
    apiFetch("/graph")
      .then((data: { nodes: GraphNode[]; edges: GraphEdge[] }) => {
        const { w, h } = dimensions;
        simRef.current = data.nodes.map(n => ({
          ...n,
          x: w / 2 + (Math.random() - 0.5) * w * 0.3,
          y: h / 2 + (Math.random() - 0.5) * h * 0.3,
          vx: 0,
          vy: 0,
        }));
        edgesRef.current = data.edges;
        initialPlacement(simRef.current, w, h);
        runSimulation(simRef.current, edgesRef.current, w, h, SIM_TICKS);
        const simTargets   = buildSimTargets(simRef.current);
        targetRef.current  = simTargets;
        displayRef.current = new Map(Array.from(simTargets, ([id, p]) => [id, { ...p }]));
        setTick(t => t + 1);

        // Compute containment depths from identity and default-collapse depth >= 2
        const childrenForDepth = new Map<string, Set<string>>();
        for (const e of data.edges) {
          if (!NB_CONTAINMENT_TYPES.has(e.type)) continue;
          const parent = (e.type === "member_of" || e.type === "studied_at") ? e.target : e.source;
          const child  = (e.type === "member_of" || e.type === "studied_at") ? e.source : e.target;
          if (!childrenForDepth.has(parent)) childrenForDepth.set(parent, new Set());
          childrenForDepth.get(parent)!.add(child);
        }
        const depths = new Map<string, number>();
        const bfsQueue: [string, number][] = [["identity", 0]];
        while (bfsQueue.length) {
          const [id, d] = bfsQueue.shift()!;
          if (depths.has(id)) continue;
          depths.set(id, d);
          for (const child of childrenForDepth.get(id) ?? []) {
            if (!depths.has(child)) bfsQueue.push([child, d + 1]);
          }
        }
        // Collapse everything at depth >= 2 by default
        setCollapsed(new Set([...depths.entries()].filter(([, d]) => d >= 2).map(([id]) => id)));
        setNbDepths(depths);
      })
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadGraph(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── selection → update animation targets ──────────────────────────────────

  useEffect(() => {
    if (!simRef.current.length) return;
    const { w, h } = dimensions;
    if (selected) {
      targetRef.current = computeFocusTargets(selected.id, simRef.current, edgesRef.current, w, h);
    } else {
      targetRef.current = buildSimTargets(simRef.current);
    }
    startAnim();
  }, [selected, dimensions]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── fetch node body + edges when selection changes ───────────────────────

  useEffect(() => {
    if (!selected) { setNodeDetail(null); return; }
    setNodeDetailLoading(true);
    apiFetch(`/nodes/${selected.id}`)
      .then((d: Record<string, unknown>) =>
        setNodeDetail({ body: d.body as string, edges: d.edges as NodeDetailEdge[] })
      )
      .catch(() => setNodeDetail(null))
      .finally(() => setNodeDetailLoading(false));
  }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => cancelAnimationFrame(animRef.current), []);

  // ── coordinate helpers ───────────────────────────────────────────────────

  function getSvgPoint(e: React.MouseEvent): { x: number; y: number } {
    const svg = svgRef.current!;
    const pt  = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const sp = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    return { x: sp.x, y: sp.y };
  }

  function toWorld(svgX: number, svgY: number): { x: number; y: number } {
    const { x, y, scale } = transformRef.current;
    return { x: (svgX - x) / scale, y: (svgY - y) / scale };
  }

  // ── node drag ────────────────────────────────────────────────────────────

  function onNodeMouseDown(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    const sp = getSvgPoint(e);
    const wp = toWorld(sp.x, sp.y);
    const dp = displayRef.current.get(id);
    if (dp) draggingRef.current = { id, ox: wp.x - dp.x, oy: wp.y - dp.y };
  }

  // ── background pan ───────────────────────────────────────────────────────

  function onSvgPanStart(e: React.MouseEvent) {
    const sp = getSvgPoint(e);
    panningRef.current = {
      startX: sp.x, startY: sp.y,
      initX: transformRef.current.x, initY: transformRef.current.y,
    };
  }

  function onSvgMouseMove(e: React.MouseEvent) {
    if (draggingRef.current) {
      const sp = getSvgPoint(e);
      const wp = toWorld(sp.x, sp.y);
      const { id, ox, oy } = draggingRef.current;
      const nx   = wp.x - ox;
      const ny   = wp.y - oy;
      const node = simRef.current.find(n => n.id === id);
      if (node) {
        node.x = nx; node.y = ny; node.vx = 0; node.vy = 0;
        const cur = displayRef.current.get(id) ?? { x: nx, y: ny, r: NODE_R_BASE, opacity: 1 };
        displayRef.current.set(id, { x: nx, y: ny, r: cur.r, opacity: cur.opacity });
        targetRef.current.set(id,  { x: nx, y: ny, r: cur.r, opacity: cur.opacity });
        setTick(t => t + 1);
        setSelected({ ...node });
      }
      return;
    }
    if (panningRef.current) {
      const sp = getSvgPoint(e);
      const { startX, startY, initX, initY } = panningRef.current;
      transformRef.current = {
        ...transformRef.current,
        x: initX + (sp.x - startX),
        y: initY + (sp.y - startY),
      };
      setTick(t => t + 1);
    }
  }

  function onSvgMouseUp() {
    draggingRef.current = null;
    panningRef.current  = null;
  }

  // ── wheel zoom ───────────────────────────────────────────────────────────

  function onSvgWheel(e: React.WheelEvent) {
    e.preventDefault();
    const sp = getSvgPoint(e);
    const { x, y, scale } = transformRef.current;
    const factor   = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const newScale = Math.min(5, Math.max(0.15, scale * factor));
    const newX = sp.x - (sp.x - x) * (newScale / scale);
    const newY = sp.y - (sp.y - y) * (newScale / scale);
    transformRef.current = { x: newX, y: newY, scale: newScale };
    setTick(t => t + 1);
  }

  function zoomBy(factor: number) {
    const { w, h } = dimensions;
    const cx = w / 2, cy = h / 2;
    const { x, y, scale } = transformRef.current;
    const newScale = Math.min(5, Math.max(0.15, scale * factor));
    const newX = cx - (cx - x) * (newScale / scale);
    const newY = cy - (cy - y) * (newScale / scale);
    transformRef.current = { x: newX, y: newY, scale: newScale };
    setTick(t => t + 1);
  }

  function resetTransform() {
    transformRef.current = { x: 0, y: 0, scale: 1 };
    setTick(t => t + 1);
  }

  // ── edge management ──────────────────────────────────────────────────────

  async function deleteEdge(edgeId: string) {
    try {
      await apiFetch(`/edges/${edgeId}`, { method: "DELETE" });
      edgesRef.current = edgesRef.current.filter(e => e.id !== edgeId);
      setNodeDetail(prev =>
        prev ? { ...prev, edges: prev.edges.filter(e => e.id !== edgeId) } : null
      );
      setSelected(s => s ? { ...s, edge_count: Math.max(0, s.edge_count - 1) } : null);
      setTick(t => t + 1);
    } catch (e: unknown) {
      console.error("Delete edge failed:", e);
    }
  }

  async function refreshAfterEdgeAdd() {
    if (!selected) return;
    setShowAddEdge(false);
    const d = await apiFetch(`/nodes/${selected.id}`);
    setNodeDetail({ body: d.body, edges: d.edges });
    setSelected(s => s ? { ...s, edge_count: (d.edges as NodeDetailEdge[]).length } : null);
    const graphData = await apiFetch("/graph");
    edgesRef.current = graphData.edges;
    setTick(t => t + 1);
  }

  // ── derived ────────────────────────────────────────────────────────────────

  const inFocusMode = selected !== null;
  const allTypes    = [...new Set(simRef.current.map(n => n.type))].sort();

  // ── containment tree (all nodes, proper parent-child direction) ───────────
  const containmentChildrenMap = new Map<string, Set<string>>();
  for (const e of edgesRef.current) {
    if (!NB_CONTAINMENT_TYPES.has(e.type)) continue;
    // member_of / studied_at are semantically reversed (child → parent in the edge)
    const parent = (e.type === "member_of" || e.type === "studied_at") ? e.target : e.source;
    const child  = (e.type === "member_of" || e.type === "studied_at") ? e.source : e.target;
    if (!containmentChildrenMap.has(parent)) containmentChildrenMap.set(parent, new Set());
    containmentChildrenMap.get(parent)!.add(child);
  }

  // All nodes reachable from identity via containment (these are "in" the graph)
  const inGraphIds = new Set<string>(["identity"]);
  {
    const stack = ["identity"];
    while (stack.length) {
      const id = stack.pop()!;
      for (const child of containmentChildrenMap.get(id) ?? []) {
        if (!inGraphIds.has(child)) { inGraphIds.add(child); stack.push(child); }
      }
    }
  }

  // Recursively hide all descendants of collapsed nodes.
  // A child is only folded if its BFS depth is strictly greater than its parent's depth,
  // meaning it has no shorter path from identity (prevents sibling cross-links from hiding nodes).
  const foldedNodeIds = new Set<string>();
  {
    const stack: string[] = [];
    for (const parentId of collapsed) {
      const parentDepth = nbDepths.get(parentId) ?? Infinity;
      for (const child of containmentChildrenMap.get(parentId) ?? []) {
        const childDepth = nbDepths.get(child) ?? Infinity;
        if (!foldedNodeIds.has(child) && childDepth > parentDepth) {
          foldedNodeIds.add(child);
          stack.push(child);
        }
      }
    }
    while (stack.length) {
      const id = stack.pop()!;
      const idDepth = nbDepths.get(id) ?? Infinity;
      for (const child of containmentChildrenMap.get(id) ?? []) {
        const childDepth = nbDepths.get(child) ?? Infinity;
        if (!foldedNodeIds.has(child) && childDepth > idDepth) {
          foldedNodeIds.add(child);
          stack.push(child);
        }
      }
    }
  }

  // Orphans: nodes not reachable from identity through containment edges
  const orphanNodes = simRef.current.filter(n =>
    n.id !== "identity" && n.type !== "system" && !inGraphIds.has(n.id)
  );
  const orphanCount = orphanNodes.length;

  const visibleNodes = simRef.current.filter(n =>
    (typeFilter === "all" || n.type === typeFilter) &&
    !foldedNodeIds.has(n.id)
  );

  const visibleEdges = edgesRef.current.filter(e => {
    // hide edges to/from folded nodes
    if (foldedNodeIds.has(e.source) || foldedNodeIds.has(e.target)) return false;
    if (typeFilter !== "all") {
      const sn = simRef.current.find(n => n.id === e.source);
      const tn = simRef.current.find(n => n.id === e.target);
      if (sn?.type !== typeFilter && tn?.type !== typeFilter) return false;
    }
    if (inFocusMode) {
      const sp = targetRef.current.get(e.source);
      const tp = targetRef.current.get(e.target);
      return !!(sp && tp && sp.opacity > 0.3 && tp.opacity > 0.3);
    }
    return true;
  });

  // ── render ─────────────────────────────────────────────────────────────────

  if (loading) return (
    <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">Loading graph…</div>
  );
  if (err) return (
    <div className="flex-1 flex items-center justify-center text-red-500 text-sm">{err}</div>
  );

  return (
    <div className="flex flex-col h-full min-h-0">

      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-200 flex-shrink-0 flex-wrap bg-white">
        <button
          onClick={loadGraph}
          title="Reload graph"
          className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded"
        >↺ Reload</button>
        <div className="h-4 border-r border-gray-200" />

        {/* Type filters — color dot always visible → doubles as the legend */}
        <button
          onClick={() => setTypeFilter("all")}
          className={`text-xs px-2 py-0.5 rounded-full ${typeFilter === "all" ? "bg-gray-800 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
        >All</button>
        {allTypes.map(t => (
          <button
            key={t}
            onClick={() => { setTypeFilter(t === typeFilter ? "all" : t); setSelected(null); }}
            className="text-xs px-2 py-0.5 rounded-full flex items-center gap-1 transition-all"
            style={{
              backgroundColor: typeFilter === t ? (TYPE_FILL[t] ?? "#9ca3af") : "#f3f4f6",
              color: typeFilter === t ? "white" : "#374151",
            }}
            title={t}
          >
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: typeFilter === t ? "rgba(255,255,255,0.75)" : (TYPE_FILL[t] ?? "#9ca3af") }}
            />
            {t}
          </button>
        ))}

        {selected && (
          <>
            <div className="h-4 border-r border-gray-200" />
            <span className="text-xs text-indigo-600 font-medium">
              Focus: <span className="font-mono">{selected.title}</span>
            </span>
            <button
              onClick={() => setSelected(null)}
              className="text-xs text-gray-400 hover:text-gray-700 bg-gray-100 px-2 py-0.5 rounded-full"
            >✕ clear</button>
          </>
        )}

        <span className="ml-auto flex items-center gap-2 text-xs text-gray-400">
          {orphanCount > 0 && (
            <button
              onClick={() => setShowOrphanPanel(v => !v)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded-full border font-medium transition-colors ${
                showOrphanPanel
                  ? "bg-amber-500 text-white border-amber-500"
                  : "bg-amber-50 text-amber-600 border-amber-200 hover:bg-amber-100"
              }`}
              title="Show nodes not connected to any notebook"
            >
              ⚠ {orphanCount} not in notebook
            </button>
          )}
          {visibleNodes.length} nodes · {visibleEdges.length} edges
        </span>
        <button
          onClick={() => setShowMemoryChat(v => !v)}
          className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
            showMemoryChat
              ? "bg-indigo-600 text-white border-indigo-600"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200 border-gray-200"
          }`}
        >🧠 Chat</button>
      </div>

      {/* Graph canvas + side panels */}
      <div className="flex-1 relative min-h-0 flex">
        <svg
          ref={svgRef}
          className="flex-1 h-full select-none"
          style={{ cursor: panningRef.current ? "grabbing" : "default" }}
          onMouseMove={onSvgMouseMove}
          onMouseUp={onSvgMouseUp}
          onMouseLeave={onSvgMouseUp}
          onWheel={onSvgWheel}
        >
          <defs>
            <marker id="arrow" markerWidth="8" markerHeight="8" refX="18" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 z" fill="#cbd5e1" />
            </marker>
          </defs>

          {/* Background rect for pan/deselect — outside the transform group */}
          <rect
            x={-10000} y={-10000} width={20000} height={20000}
            fill="transparent"
            style={{ cursor: panningRef.current ? "grabbing" : "grab" }}
            onMouseDown={onSvgPanStart}
            onClick={() => setSelected(null)}
          />

          {/* All graph elements inside pan/zoom transform */}
          <g transform={`translate(${transformRef.current.x},${transformRef.current.y}) scale(${transformRef.current.scale})`}>

            {/* Tier ring guides */}
            {!inFocusMode && TIER_RADII.slice(1).map((r, i) => (
              <circle
                key={`ring-${i}`}
                cx={dimensions.w / 2}
                cy={dimensions.h / 2}
                r={r}
                fill="none"
                stroke="#f1f5f9"
                strokeWidth={1}
                strokeDasharray="4 6"
              />
            ))}

            {/* Edges */}
            {visibleEdges.map(e => {
              const sp = displayRef.current.get(e.source);
              const tp = displayRef.current.get(e.target);
              if (!sp || !tp) return null;
              const mx = (sp.x + tp.x) / 2;
              const my = (sp.y + tp.y) / 2;
              const hovered = hoveredEdge === e.id;
              return (
                <g key={e.id}>
                  <line
                    x1={sp.x} y1={sp.y} x2={tp.x} y2={tp.y}
                    stroke={hovered ? "#6366f1" : "#cbd5e1"}
                    strokeWidth={hovered ? 2 : 1}
                    strokeOpacity={inFocusMode ? 0.55 : 0.70}
                    markerEnd="url(#arrow)"
                    onMouseEnter={() => setHoveredEdge(e.id)}
                    onMouseLeave={() => setHoveredEdge(null)}
                    className="cursor-pointer"
                  />
                  {hovered && (
                    <text x={mx} y={my - 5} textAnchor="middle" fontSize={10} fill="#6366f1">
                      {e.label || e.type}
                    </text>
                  )}
                </g>
              );
            })}

            {/* Nodes */}
            {visibleNodes.map(n => {
              const pos = displayRef.current.get(n.id);
              if (!pos) return null;
              const isSelected  = selected?.id === n.id;
              const fill        = TYPE_FILL[n.type] ?? "#9ca3af";
              const r           = pos.r;
              const isFocusShow = !inFocusMode || pos.opacity > 0.25;
              const abbr        = TYPE_ABBR[n.type] ?? n.type.slice(0, 2).toUpperCase();
              const innerLabel  = isSelected
                ? (n.title.length > 10 ? n.title.slice(0, 9) + "…" : n.title)
                : abbr;
              const showBelowLabel = !inFocusMode || pos.opacity > 0.25;
              const belowTitle  = n.title.length > 20 ? n.title.slice(0, 19) + "…" : n.title;

              return (
                <g
                  key={n.id}
                  transform={`translate(${pos.x},${pos.y})`}
                  opacity={pos.opacity}
                  onMouseDown={e => onNodeMouseDown(e, n.id)}
                  onClick={e => { e.stopPropagation(); setSelected(n); }}
                  className="cursor-pointer"
                >
                  {isSelected && (
                    <circle r={r + 8} fill={fill} fillOpacity={0.15} />
                  )}
                  <circle
                    r={r}
                    fill={fill}
                    fillOpacity={0.92}
                    stroke={isSelected ? "#1e1b4b" : isFocusShow ? "white" : "none"}
                    strokeWidth={isSelected ? 2.5 : 1.5}
                  />
                  {n.has_document && (
                    <circle
                      cx={r * 0.72}
                      cy={-r * 0.72}
                      r={4}
                      fill="#f59e0b"
                      stroke="white"
                      strokeWidth={1}
                      style={{ pointerEvents: "none" }}
                    />
                  )}
                  {/* Fold/unfold toggle — shown on any node that has containment children */}
                  {(containmentChildrenMap.get(n.id)?.size ?? 0) > 0 && (
                    <g
                      transform={`translate(${r + 2},${-r - 2})`}
                      onClick={e => { e.stopPropagation(); toggleCollapse(n.id); }}
                      className="cursor-pointer"
                    >
                      <circle
                        r={8}
                        fill={collapsed.has(n.id) ? "#6366f1" : "#e5e7eb"}
                        stroke="white"
                        strokeWidth={1.5}
                      />
                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        fontSize={9}
                        fill={collapsed.has(n.id) ? "white" : "#6b7280"}
                        fontWeight="700"
                        style={{ pointerEvents: "none", userSelect: "none" }}
                      >
                        {collapsed.has(n.id) ? "▸" : "▾"}
                      </text>
                    </g>
                  )}
                  {/* Hidden child count badge when collapsed */}
                  {collapsed.has(n.id) && (containmentChildrenMap.get(n.id)?.size ?? 0) > 0 && (
                    <text
                      y={r + 26}
                      textAnchor="middle"
                      fontSize={9}
                      fill="#6366f1"
                      fontWeight="600"
                      stroke="white"
                      strokeWidth={2.5}
                      paintOrder="stroke fill"
                      style={{ pointerEvents: "none", userSelect: "none" }}
                    >
                      +{containmentChildrenMap.get(n.id)?.size}
                    </text>
                  )}
                  <text
                    textAnchor="middle"
                    dominantBaseline="central"
                    fontSize={isSelected ? 13 : 11}
                    fill="white"
                    fontWeight="700"
                    style={{ pointerEvents: "none", userSelect: "none" }}
                  >
                    {innerLabel}
                  </text>
                  {showBelowLabel && (
                    <text
                      y={r + 13}
                      textAnchor="middle"
                      fontSize={isSelected ? 12 : 10}
                      fontWeight={isSelected ? "700" : "500"}
                      fill="#111827"
                      stroke="white"
                      strokeWidth={3}
                      paintOrder="stroke fill"
                      style={{ pointerEvents: "none", userSelect: "none" }}
                    >
                      {belowTitle}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        {/* Zoom controls */}
        <div className="absolute bottom-4 left-4 flex flex-col gap-1 z-10">
          <button
            onClick={() => zoomBy(1.25)}
            className="w-7 h-7 bg-white border border-gray-200 rounded shadow-sm text-gray-600 hover:bg-gray-50 text-sm font-medium flex items-center justify-center"
            title="Zoom in"
          >+</button>
          <button
            onClick={() => zoomBy(1 / 1.25)}
            className="w-7 h-7 bg-white border border-gray-200 rounded shadow-sm text-gray-600 hover:bg-gray-50 text-sm font-medium flex items-center justify-center"
            title="Zoom out"
          >−</button>
          <button
            onClick={resetTransform}
            className="w-7 h-7 bg-white border border-gray-200 rounded shadow-sm text-gray-400 hover:bg-gray-50 text-xs flex items-center justify-center"
            title="Reset zoom & pan"
          >⊙</button>
        </div>

        {/* Node detail panel */}
        {selected && (
          <div
            className="w-72 flex-shrink-0 border-l border-gray-200 bg-white flex flex-col min-h-0"
            style={{ maxHeight: "100%" }}
          >
            {/* Header */}
            <div className="px-4 py-3 border-b border-gray-100 flex-shrink-0">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold text-gray-900 text-sm leading-tight flex-1 min-w-0 truncate">
                  {selected.title}
                </h3>
                <button
                  onClick={() => setSelected(null)}
                  className="text-gray-400 hover:text-gray-600 flex-shrink-0 text-base leading-none"
                >✕</button>
              </div>
              <div className="flex gap-1 flex-wrap mt-2">
                <span
                  className="px-2 py-0.5 rounded-full text-white text-xs font-medium"
                  style={{ backgroundColor: TYPE_FILL[selected.type] ?? "#9ca3af" }}
                >{selected.type}</span>
                <span className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 text-xs">tier {selected.tier}</span>
                {selected.roles.map(r => (
                  <span key={r} className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-xs">{r}</span>
                ))}
              </div>
            </div>

            {/* Scrollable body */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0 text-xs">

              {/* Content */}
              <section>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">Content</p>
                {nodeDetailLoading ? (
                  <p className="text-gray-400 italic">Loading…</p>
                ) : nodeDetail?.body ? (
                  <div className="prose prose-xs max-w-none bg-gray-50 rounded-lg p-2.5 max-h-64 overflow-y-auto border border-gray-100 text-[11px] [&_h1]:text-xs [&_h2]:text-xs [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:text-[10px] [&_h3]:font-semibold [&_table]:text-[10px] [&_td]:p-0.5 [&_th]:p-0.5 [&_a]:text-indigo-600 [&_a]:underline [&_strong]:font-semibold [&_ul]:pl-4 [&_ol]:pl-4 [&_li]:my-0 [&_p]:my-0.5">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{nodeDetail.body}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="text-gray-400 italic">No content</p>
                )}
              </section>

              {/* Open in Knowledge */}
              {onNavigateToNode && (
                <button
                  onClick={() => onNavigateToNode(selected.id)}
                  className="w-full text-xs text-indigo-600 border border-indigo-200 rounded-lg px-3 py-2 hover:bg-indigo-50 flex items-center justify-center gap-1.5 font-medium"
                >
                  ✏ Open in Knowledge to edit
                </button>
              )}

              {/* Relationships */}
              <section>
                <div className="flex items-center justify-between mb-1.5">
                  <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">
                    Relationships ({selected.edge_count})
                  </p>
                  <button
                    onClick={() => setShowAddEdge(true)}
                    className="text-[10px] text-indigo-600 hover:text-indigo-800 font-medium bg-indigo-50 px-1.5 py-0.5 rounded"
                  >+ Add</button>
                </div>

                {/* Rich edge list (from API fetch) */}
                {nodeDetail?.edges.map(e => {
                  const otherId  = e.direction === "outgoing" ? e.target_id : e.source_id;
                  const otherSim = simRef.current.find(n => n.id === otherId);
                  return (
                    <div key={e.id} className="flex items-center gap-1 py-1 group border-b border-gray-50 last:border-0">
                      <span className="text-gray-400 flex-shrink-0">{e.direction === "outgoing" ? "→" : "←"}</span>
                      <button
                        className="flex-1 text-left text-gray-700 hover:underline hover:text-indigo-600 truncate"
                        onClick={() => otherSim && setSelected(otherSim)}
                      >{e.other_title}</button>
                      <span
                        className="flex-shrink-0 px-1 py-0.5 rounded text-[9px] font-medium text-white"
                        style={{ backgroundColor: TYPE_FILL[e.other_type] ?? "#9ca3af" }}
                      >{e.type}</span>
                      <button
                        onClick={() => deleteEdge(e.id)}
                        className="text-gray-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 ml-0.5"
                        title="Delete relationship"
                      >✕</button>
                    </div>
                  );
                })}

                {/* Fallback: local edges while detail is loading */}
                {!nodeDetail && edgesRef.current
                  .filter(e => e.source === selected.id || e.target === selected.id)
                  .map(e => {
                    const otherId = e.source === selected.id ? e.target : e.source;
                    const other   = simRef.current.find(n => n.id === otherId);
                    return (
                      <div key={e.id} className="flex items-center gap-1 py-0.5">
                        <span className="text-gray-400 flex-shrink-0">{e.source === selected.id ? "→" : "←"}</span>
                        <span
                          className="flex-1 truncate text-gray-700 cursor-pointer hover:underline hover:text-indigo-600"
                          onClick={() => other && setSelected(other)}
                        >{other?.title ?? otherId}</span>
                        <span className="text-indigo-500 flex-shrink-0 text-[9px]">{e.type}</span>
                      </div>
                    );
                  })
                }
              </section>

              <p className="text-gray-300 font-mono text-[9px] break-all">{selected.id}</p>
            </div>
          </div>
        )}

        {/* Memory chat sidebar */}
        {showMemoryChat && <MemoryChatSidebar token={token} />}

        {/* Orphan nodes panel */}
        {showOrphanPanel && orphanNodes.length > 0 && (
          <div className="absolute top-0 right-0 z-20 bg-white border-l border-b border-gray-200 shadow-xl w-72 flex flex-col max-h-full">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
              <div>
                <h4 className="text-sm font-semibold text-gray-900">Not in any notebook</h4>
                <p className="text-xs text-gray-400 mt-0.5">{orphanNodes.length} node{orphanNodes.length !== 1 ? "s" : ""}</p>
              </div>
              <button onClick={() => setShowOrphanPanel(false)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>
            <p className="px-4 py-2.5 text-xs text-gray-500 border-b border-gray-100 flex-shrink-0">
              Click a node to select it, then use <strong>+ Add</strong> in the relationship panel to wire it into the right place.
            </p>
            <div className="flex-1 overflow-y-auto py-1">
              {orphanNodes.map(n => (
                <button
                  key={n.id}
                  onClick={() => { setSelected(n); setShowOrphanPanel(false); }}
                  className="w-full text-left flex items-center gap-2 px-4 py-2 hover:bg-gray-50 border-b border-gray-50 last:border-0"
                >
                  <span
                    className="px-1.5 py-0.5 rounded text-white text-[10px] font-medium flex-shrink-0"
                    style={{ backgroundColor: TYPE_FILL[n.type] ?? "#9ca3af" }}
                  >{n.type}</span>
                  <span className="text-xs text-gray-700 truncate flex-1">{n.title}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Add-edge modal */}
      {showAddEdge && selected && (
        <AddEdgeModal
          nodeId={selected.id}
          allNodes={simRef.current}
          onClose={() => setShowAddEdge(false)}
          onCreated={refreshAfterEdgeAdd}
        />
      )}
    </div>
  );
}
