import { useEffect, useState, useRef, useCallback } from "react";
import { useKnowledge, NotebookSummary, apiFetch, TYPE_COLORS } from "./KnowledgeContext";

function NotebookRow({
  nb,
  active,
  onClick,
  onMoveUp,
  onMoveDown,
  isFirst,
  isLast,
}: {
  nb: NotebookSummary;
  active: boolean;
  onClick: () => void;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
  isFirst: boolean;
  isLast: boolean;
}) {
  return (
    <div
      className={`group relative flex items-center border-b border-gray-100 transition-colors ${
        active ? "bg-indigo-50 border-l-2 border-l-indigo-500" : "hover:bg-gray-50"
      }`}
    >
      <button
        onClick={onClick}
        className="flex-1 text-left px-3 py-2.5 flex items-center gap-2.5 min-w-0"
      >
        <span className="text-lg flex-shrink-0">{nb.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-gray-900 truncate">{nb.title}</div>
          <div className="text-xs text-gray-400">{nb.page_count} pages</div>
        </div>
      </button>
      {/* Up/down reorder arrows — visible on hover */}
      <div className="flex-shrink-0 flex flex-col opacity-0 group-hover:opacity-100 transition-opacity pr-1">
        <button
          onClick={(e) => { e.stopPropagation(); onMoveUp?.(); }}
          disabled={isFirst}
          className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-indigo-600 disabled:opacity-20 disabled:cursor-default"
          title="Move up"
        >
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M14.77 12.79a.75.75 0 01-1.06-.02L10 8.832l-3.71 3.938a.75.75 0 01-1.08-1.04l4.25-4.5a.75.75 0 011.08 0l4.25 4.5a.75.75 0 01-.02 1.06z" clipRule="evenodd" />
          </svg>
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onMoveDown?.(); }}
          disabled={isLast}
          className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-indigo-600 disabled:opacity-20 disabled:cursor-default"
          title="Move down"
        >
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
          </svg>
        </button>
      </div>
    </div>
  );
}

function NewNotebookModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [icon, setIcon] = useState("📓");
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const handleCreate = useCallback(async () => {
    if (!title.trim()) return;
    setSaving(true);
    try {
      // Create the notebook node
      const node = await apiFetch("/nodes", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          type: "notebook",
          body: "",
          roles: ["public"],
          metadata: { notebook_root: true, icon },
        }),
      });
      // Wire identity → has → notebook
      await apiFetch("/edges", {
        method: "POST",
        body: JSON.stringify({
          source_id: "identity",
          target_id: node.id,
          type: "has",
          label: "",
          roles: ["public"],
        }),
      });
      onCreated();
      onClose();
    } catch (e: any) {
      alert("Failed to create notebook: " + e.message);
    } finally {
      setSaving(false);
    }
  }, [title, icon, onClose, onCreated]);

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-[380px] p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">New Notebook</h3>
        <div className="space-y-3">
          <div className="flex gap-2">
            <input
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              className="w-12 text-center text-xl border border-gray-200 rounded-lg focus:ring-2 focus:ring-indigo-200 outline-none"
              maxLength={2}
            />
            <input
              ref={inputRef}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              placeholder="Notebook name"
              className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-200 outline-none"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            onClick={handleCreate}
            disabled={!title.trim() || saving}
            className="px-4 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function NotebookSidebar({ readOnly }: { readOnly?: boolean }) {
  const {
    notebooks, currentNotebookId, selectNotebook, loadNotebooks,
    orphanNodes, loadingOrphans, loadOrphans, selectPage, currentPageId,
  } = useKnowledge();
  const [showOrphans, setShowOrphans] = useState(false);
  const [showNewModal, setShowNewModal] = useState(false);

  useEffect(() => {
    loadNotebooks();
  }, [loadNotebooks]);

  // Auto-select first notebook
  useEffect(() => {
    if (notebooks.length > 0 && !currentNotebookId && !showOrphans) {
      selectNotebook(notebooks[0].id);
    }
  }, [notebooks, currentNotebookId, selectNotebook, showOrphans]);

  const handleReorder = useCallback(async (idx: number, direction: "up" | "down") => {
    const swapIdx = direction === "up" ? idx - 1 : idx + 1;
    if (swapIdx < 0 || swapIdx >= notebooks.length) return;
    const a = notebooks[idx];
    const b = notebooks[swapIdx];
    // Assign order values based on current positions, then swap
    const orderA = idx * 10;
    const orderB = swapIdx * 10;
    try {
      await Promise.all([
        apiFetch(`/nodes/${a.id}`, {
          method: "PUT",
          body: JSON.stringify({ metadata: { order: orderB } }),
        }),
        apiFetch(`/nodes/${b.id}`, {
          method: "PUT",
          body: JSON.stringify({ metadata: { order: orderA } }),
        }),
      ]);
      await loadNotebooks();
    } catch (e: any) {
      alert("Failed to reorder: " + e.message);
    }
  }, [notebooks, loadNotebooks]);

  return (
    <div className="w-48 flex-shrink-0 border-r border-gray-200 flex flex-col min-h-0 bg-white">
      <div className="px-3 py-2.5 border-b border-gray-200 flex items-center">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 flex-1">Notebooks</h3>
        {!readOnly && (
        <button
          onClick={() => setShowNewModal(true)}
          className="w-5 h-5 flex items-center justify-center text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded transition-colors"
          title="New notebook"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
        </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {notebooks.map((nb, idx) => (
          <NotebookRow
            key={nb.id}
            nb={nb}
            active={currentNotebookId === nb.id && !showOrphans}
            onClick={() => { setShowOrphans(false); selectNotebook(nb.id); }}
            onMoveUp={() => handleReorder(idx, "up")}
            onMoveDown={() => handleReorder(idx, "down")}
            isFirst={idx === 0}
            isLast={idx === notebooks.length - 1}
          />
        ))}
        {notebooks.length === 0 && (
          <p className="p-4 text-sm text-gray-400 italic">No notebooks found.</p>
        )}

        {/* Unsorted / orphan nodes section */}
        <button
          onClick={() => {
            if (!showOrphans) loadOrphans();
            setShowOrphans(v => !v);
          }}
          className={`w-full text-left px-3 py-2.5 flex items-center gap-2.5 border-t border-gray-200 transition-colors ${
            showOrphans ? "bg-amber-50 border-l-2 border-l-amber-400" : "hover:bg-gray-50"
          }`}
        >
          <span className="text-lg flex-shrink-0">📦</span>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-gray-900">Unsorted</div>
            <div className="text-xs text-gray-400">
              {loadingOrphans ? "loading…" : `${orphanNodes.length} node${orphanNodes.length !== 1 ? "s" : ""}`}
            </div>
          </div>
        </button>

        {/* Orphan node list (inline) */}
        {showOrphans && (
          <div className="border-t border-gray-100">
            {loadingOrphans && (
              <p className="px-3 py-2 text-xs text-gray-400 italic">Loading…</p>
            )}
            {!loadingOrphans && orphanNodes.length === 0 && (
              <p className="px-3 py-2 text-xs text-gray-400 italic">All nodes are in notebooks.</p>
            )}
            {!loadingOrphans && orphanNodes.map(n => (
              <button
                key={n.id}
                onClick={() => selectPage(n.id)}
                className={`w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-amber-50 transition-colors border-b border-gray-50 ${
                  currentPageId === n.id ? "bg-amber-100" : ""
                }`}
              >
                <span className={`text-[10px] px-1 py-0.5 rounded font-medium flex-shrink-0 ${TYPE_COLORS[n.type] ?? "bg-gray-100 text-gray-600"}`}>
                  {n.type}
                </span>
                <span className="text-xs text-gray-800 truncate flex-1">{n.title}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {showNewModal && (
        <NewNotebookModal onClose={() => setShowNewModal(false)} onCreated={loadNotebooks} />
      )}
    </div>
  );
}
