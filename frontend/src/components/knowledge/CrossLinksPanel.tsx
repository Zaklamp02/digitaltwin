import { useState, useCallback, useRef, useEffect } from "react";
import { useKnowledge, EdgeInfo, TYPE_COLORS, EDGE_TYPES, CONTAINMENT_EDGE_TYPES, apiFetch } from "./KnowledgeContext";

function TypeBadge({ type }: { type: string }) {
  return (
    <span className={`text-[10px] font-medium px-1 py-0.5 rounded ${TYPE_COLORS[type] ?? "bg-gray-100 text-gray-700"}`}>
      {type}
    </span>
  );
}

// ── Add Cross-Link inline form ────────────────────────────────────────────────

function AddCrossLinkForm({ nodeId, onAdded, onCancel }: { nodeId: string; onAdded: () => void; onCancel: () => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ id: string; title: string; type: string }[]>([]);
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null);
  const [edgeType, setEdgeType] = useState("relates_to");
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const crossLinkTypes = EDGE_TYPES.filter((t) => !CONTAINMENT_EDGE_TYPES.has(t));

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) { setResults([]); return; }
    try {
      const nodes = await apiFetch(`/nodes?search=${encodeURIComponent(q)}`);
      setResults(nodes.filter((n: any) => n.id !== nodeId).slice(0, 8));
    } catch { setResults([]); }
  }, [nodeId]);

  const handleQueryChange = (val: string) => {
    setQuery(val);
    setSelectedTarget(null);
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => doSearch(val), 300);
  };

  const handleCreate = useCallback(async () => {
    if (!selectedTarget) return;
    setSaving(true);
    try {
      await apiFetch("/edges", {
        method: "POST",
        body: JSON.stringify({
          source_id: nodeId,
          target_id: selectedTarget,
          type: edgeType,
          label: "",
          roles: ["public"],
        }),
      });
      onAdded();
    } catch (e: any) {
      alert("Failed to create link: " + e.message);
    } finally {
      setSaving(false);
    }
  }, [nodeId, selectedTarget, edgeType, onAdded]);

  return (
    <div className="px-3 py-2 border-t border-gray-200 space-y-2">
      <select
        value={edgeType}
        onChange={(e) => setEdgeType(e.target.value)}
        className="w-full px-2 py-1 text-xs border border-gray-200 rounded bg-white outline-none focus:ring-1 focus:ring-indigo-200"
      >
        {crossLinkTypes.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => handleQueryChange(e.target.value)}
        placeholder="Search for a node…"
        className="w-full px-2 py-1 text-xs border border-gray-200 rounded outline-none focus:ring-1 focus:ring-indigo-200"
      />
      {results.length > 0 && !selectedTarget && (
        <div className="max-h-32 overflow-y-auto border border-gray-100 rounded">
          {results.map((r) => (
            <button
              key={r.id}
              onClick={() => { setSelectedTarget(r.id); setQuery(r.title); }}
              className="w-full text-left px-2 py-1 text-xs hover:bg-indigo-50 flex items-center gap-1"
            >
              <span className="truncate flex-1">{r.title}</span>
              <TypeBadge type={r.type} />
            </button>
          ))}
        </div>
      )}
      <div className="flex gap-1">
        <button onClick={onCancel} className="flex-1 px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 rounded">Cancel</button>
        <button
          onClick={handleCreate}
          disabled={!selectedTarget || saving}
          className="flex-1 px-2 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "…" : "Add"}
        </button>
      </div>
    </div>
  );
}

// ── Delete edge ───────────────────────────────────────────────────────────────

function EdgeRow({ edge, onNavigate, onDelete }: { edge: EdgeInfo; onNavigate: () => void; onDelete?: () => void }) {
  const isIncoming = edge.direction === "incoming";
  return (
    <div className="flex items-center gap-1 group">
      <button
        onClick={onNavigate}
        className="flex-1 text-left flex items-center gap-1.5 py-1 px-1.5 rounded hover:bg-white transition-colors min-w-0"
      >
        {isIncoming && <TypeBadge type={edge.other_type} />}
        <span className="text-xs text-indigo-500 bg-indigo-50 px-1 rounded flex-shrink-0">{edge.type}</span>
        {!isIncoming && <span className="text-xs font-medium text-gray-700 truncate flex-1 group-hover:text-indigo-600">{edge.other_title}</span>}
        {isIncoming && <span className="text-xs font-medium text-gray-700 truncate flex-1 group-hover:text-indigo-600">{edge.other_title}</span>}
        {!isIncoming && <TypeBadge type={edge.other_type} />}
      </button>
      {onDelete && (
      <button
        onClick={onDelete}
        className="w-4 h-4 flex items-center justify-center text-gray-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
        title="Remove link"
      >
        ×
      </button>
      )}
    </div>
  );
}

export default function CrossLinksPanel({
  edges,
  nodeId,
  onRefresh,
  readOnly,
}: {
  edges: EdgeInfo[];
  nodeId: string;
  allNodes?: unknown[];
  onRefresh: () => void;
  readOnly?: boolean;
}) {
  const { selectPage } = useKnowledge();
  const [showAddForm, setShowAddForm] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("crosslinks-collapsed") === "true"; } catch { return false; }
  });

  const incoming = edges.filter((e) => e.direction === "incoming");
  const outgoing = edges.filter((e) => e.direction === "outgoing");

  const handleDeleteEdge = useCallback(async (edgeId: string) => {
    if (!confirm("Remove this cross-link?")) return;
    try {
      await apiFetch(`/edges/${edgeId}`, { method: "DELETE" });
      onRefresh();
    } catch (e: any) {
      alert("Failed to delete: " + e.message);
    }
  }, [onRefresh]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem("crosslinks-collapsed", String(next)); } catch { /* ignore */ }
      return next;
    });
  };

  // Collapsed strip
  if (collapsed) {
    return (
      <div className="w-8 flex-shrink-0 border-l border-gray-200 bg-gray-50 flex flex-col items-center pt-2">
        <button
          onClick={toggleCollapsed}
          className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-indigo-600 rounded transition-colors"
          title="Expand cross-links"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        {edges.length > 0 && (
          <span className="text-[10px] text-gray-400 mt-1">{edges.length}</span>
        )}
      </div>
    );
  }

  return (
    <div className="w-56 flex-shrink-0 border-l border-gray-200 bg-gray-50 overflow-y-auto">
      <div className="px-3 py-2.5 border-b border-gray-200 flex items-center">
        <button
          onClick={toggleCollapsed}
          className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-600 mr-1 flex-shrink-0"
          title="Collapse"
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 flex-1">Cross-links</h3>
        {!readOnly && (
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className="w-5 h-5 flex items-center justify-center text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded transition-colors"
          title="Add cross-link"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
        </button>
        )}
      </div>

      {showAddForm && (
        <AddCrossLinkForm
          nodeId={nodeId}
          onAdded={() => { setShowAddForm(false); onRefresh(); }}
          onCancel={() => setShowAddForm(false)}
        />
      )}

      {outgoing.length > 0 && (
        <div className="px-3 py-2">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">Outgoing</h4>
          <div className="space-y-0.5">
            {outgoing.map((e) => (
              <EdgeRow
                key={e.id}
                edge={e}
                onNavigate={() => selectPage(e.target_id)}
                onDelete={readOnly ? undefined : () => handleDeleteEdge(e.id)}
              />
            ))}
          </div>
        </div>
      )}

      {incoming.length > 0 && (
        <div className="px-3 py-2">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">Incoming</h4>
          <div className="space-y-0.5">
            {incoming.map((e) => (
              <EdgeRow
                key={e.id}
                edge={e}
                onNavigate={() => selectPage(e.source_id)}
                onDelete={readOnly ? undefined : () => handleDeleteEdge(e.id)}
              />
            ))}
          </div>
        </div>
      )}

      {edges.length === 0 && !showAddForm && (
        <p className="px-3 py-4 text-xs text-gray-400 italic">No cross-links.</p>
      )}
    </div>
  );
}
