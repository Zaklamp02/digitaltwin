import { useState, useCallback, useEffect, useRef } from "react";
import { useKnowledge, TreeNode, TYPE_COLORS, NODE_TYPES, apiFetch } from "./KnowledgeContext";

function TypeBadge({ type }: { type: string }) {
  return (
    <span className={`text-[10px] font-medium px-1 py-0.5 rounded ${TYPE_COLORS[type] ?? "bg-gray-100 text-gray-700"}`}>
      {type}
    </span>
  );
}

function TreeItem({
  node,
  depth,
  selectedId,
  onSelect,
  collapsedState,
  toggleCollapse,
  onContextMenu,
}: {
  node: TreeNode;
  depth: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  collapsedState: Record<string, boolean>;
  toggleCollapse: (id: string) => void;
  onContextMenu?: (e: React.MouseEvent, node: TreeNode) => void;
}) {
  const hasChildren = node.children.length > 0;
  const collapsed = collapsedState[node.id] ?? (depth >= 2);
  const isSelected = selectedId === node.id;

  return (
    <div>
      <button
        onClick={() => onSelect(node.id)}
        onContextMenu={onContextMenu ? (e) => onContextMenu(e, node) : undefined}
        className={`w-full text-left flex items-center gap-1 py-1.5 pr-2 transition-colors group ${
          isSelected
            ? "bg-indigo-50 text-indigo-900"
            : "hover:bg-gray-50 text-gray-700"
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {/* Expand/collapse caret */}
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              toggleCollapse(node.id);
            }}
            className="w-4 h-4 flex items-center justify-center text-gray-400 hover:text-gray-600 flex-shrink-0"
          >
            <svg
              className={`w-3 h-3 transition-transform ${collapsed ? "" : "rotate-90"}`}
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
            </svg>
          </button>
        ) : (
          <span className="w-4 flex-shrink-0" />
        )}

        {node.icon && <span className="text-sm flex-shrink-0">{node.icon}</span>}

        <span
          className={`text-sm truncate flex-1 ${
            hasChildren ? "font-medium" : "font-normal"
          }`}
        >
          {node.title}
        </span>

        <TypeBadge type={node.type} />

        {/* Lock icon for non-public */}
        {!node.roles.includes("public") && (
          <span className="text-[10px] text-gray-400 flex-shrink-0" title="Restricted access">🔒</span>
        )}
      </button>

      {/* Children */}
      {hasChildren && !collapsed && (
        <div>
          {node.children.map((child) => (
            <TreeItem
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
              collapsedState={collapsedState}
              toggleCollapse={toggleCollapse}
              onContextMenu={onContextMenu}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── New Page Modal ────────────────────────────────────────────────────────────

function NewPageModal({
  parentId,
  parentTitle,
  parentRoles,
  onClose,
  onCreated,
}: {
  parentId: string;
  parentTitle: string;
  parentRoles: string[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState("personal");
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const handleCreate = useCallback(async () => {
    if (!title.trim()) return;
    setSaving(true);
    try {
      const node = await apiFetch("/nodes", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          type,
          body: "",
          roles: parentRoles,
          metadata: {},
        }),
      });
      await apiFetch("/edges", {
        method: "POST",
        body: JSON.stringify({
          source_id: parentId,
          target_id: node.id,
          type: "includes",
          label: "",
          roles: parentRoles,
        }),
      });
      onCreated();
      onClose();
    } catch (e: any) {
      alert("Failed to create page: " + e.message);
    } finally {
      setSaving(false);
    }
  }, [title, type, parentId, parentRoles, onClose, onCreated]);

  const pageTypes = NODE_TYPES.filter((t) => t !== "notebook" && t !== "system");

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-[400px] p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-gray-900 mb-1">New Page</h3>
        <p className="text-xs text-gray-400 mb-4">Under {parentTitle}</p>
        <div className="space-y-3">
          <input
            ref={inputRef}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            placeholder="Page title"
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-200 outline-none"
          />
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Type</label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-200 outline-none bg-white"
            >
              {pageTypes.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
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

// ── Delete Confirmation Modal ─────────────────────────────────────────────────

function DeleteModal({
  nodeId,
  nodeTitle,
  childCount,
  onClose,
  onDeleted,
}: {
  nodeId: string;
  nodeTitle: string;
  childCount: number;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [deleting, setDeleting] = useState(false);

  const handleDelete = useCallback(async () => {
    setDeleting(true);
    try {
      await apiFetch(`/nodes/${nodeId}`, { method: "DELETE" });
      onDeleted();
      onClose();
    } catch (e: any) {
      alert("Failed to delete: " + e.message);
    } finally {
      setDeleting(false);
    }
  }, [nodeId, onClose, onDeleted]);

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-[380px] p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Delete "{nodeTitle}"?</h3>
        <p className="text-sm text-gray-600 mb-1">This action cannot be undone.</p>
        {childCount > 0 && (
          <p className="text-sm text-red-600 font-medium">
            This will also delete {childCount} child page{childCount > 1 ? "s" : ""}.
          </p>
        )}
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="px-4 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
          >
            {deleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── NotebookTree main component ───────────────────────────────────────────────

/** Find the siblings array (parent's children) that contains the given nodeId. */
function findSiblings(root: TreeNode, targetId: string): TreeNode[] | null {
  if (root.children.some((c) => c.id === targetId)) return root.children;
  for (const child of root.children) {
    const found = findSiblings(child, targetId);
    if (found) return found;
  }
  return null;
}

export default function NotebookTree({ readOnly }: { readOnly?: boolean }) {
  const { currentTree, currentNotebookId, currentPageId, selectPage, refreshTree, refreshPage } = useKnowledge();
  const [collapsedState, setCollapsedState] = useState<Record<string, boolean>>({});
  const [newPageParent, setNewPageParent] = useState<{ id: string; title: string; roles: string[] } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; title: string; childCount: number } | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    nodeId: string; x: number; y: number; node: TreeNode; siblings: TreeNode[];
  } | null>(null);

  // Persist collapsed state per notebook in localStorage
  const storageKey = `notebook-collapse-${currentNotebookId}`;

  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        setCollapsedState(JSON.parse(saved));
      } else {
        setCollapsedState({});
      }
    } catch {
      setCollapsedState({});
    }
  }, [storageKey]);

  const toggleCollapse = useCallback(
    (id: string) => {
      setCollapsedState((prev) => {
        const next = { ...prev, [id]: !prev[id] };
        try {
          localStorage.setItem(storageKey, JSON.stringify(next));
        } catch { /* ignore */ }
        return next;
      });
    },
    [storageKey]
  );

  // Close context menu on outside click
  useEffect(() => {
    if (!contextMenu) return;
    const handler = () => setContextMenu(null);
    document.addEventListener("click", handler);
    return () => document.removeEventListener("click", handler);
  }, [contextMenu]);

  // Count all descendants for delete warning
  const countDescendants = (node: TreeNode): number =>
    node.children.reduce((sum, c) => sum + 1 + countDescendants(c), 0);

  const handleContextMenu = useCallback((e: React.MouseEvent, node: TreeNode) => {
    e.preventDefault();
    const siblings = (currentTree ? findSiblings(currentTree, node.id) : null) ?? [];
    setContextMenu({ nodeId: node.id, x: e.clientX, y: e.clientY, node, siblings });
  }, [currentTree]);

  const handleMoveInTree = useCallback(async (nodeId: string, siblings: TreeNode[], direction: "up" | "down") => {
    const idx = siblings.findIndex((s) => s.id === nodeId);
    if (idx < 0) return;
    const swapIdx = direction === "up" ? idx - 1 : idx + 1;
    if (swapIdx < 0 || swapIdx >= siblings.length) return;
    const orderA = idx * 10;
    const orderB = swapIdx * 10;
    try {
      await Promise.all([
        apiFetch(`/nodes/${siblings[idx].id}`, {
          method: "PUT",
          body: JSON.stringify({ metadata: { order: orderB } }),
        }),
        apiFetch(`/nodes/${siblings[swapIdx].id}`, {
          method: "PUT",
          body: JSON.stringify({ metadata: { order: orderA } }),
        }),
      ]);
      await refreshTree();
    } catch (e: any) {
      alert("Failed to reorder: " + e.message);
    }
    setContextMenu(null);
  }, [refreshTree]);

  const handleRefresh = useCallback(async () => {
    await refreshTree();
  }, [refreshTree]);

  if (!currentTree) {
    return (
      <div className="w-60 flex-shrink-0 border-r border-gray-200 flex items-center justify-center bg-white">
        <p className="text-sm text-gray-400 italic">Select a notebook</p>
      </div>
    );
  }

  return (
    <div className="w-60 flex-shrink-0 border-r border-gray-200 flex flex-col min-h-0 bg-white">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-gray-200 flex items-center gap-2">
        <span className="text-lg">{currentTree.icon}</span>
        <button
          onClick={() => selectPage(currentTree.id)}
          className={`text-sm font-semibold truncate flex-1 text-left transition-colors ${
            currentPageId === currentTree.id
              ? "text-indigo-700"
              : "text-gray-700 hover:text-indigo-600"
          }`}
          title="View / edit this notebook's root page"
        >
          {currentTree.title}
        </button>
        {!readOnly && (
        <button
          onClick={() => setNewPageParent({ id: currentTree.id, title: currentTree.title, roles: currentTree.roles })}
          className="w-5 h-5 flex items-center justify-center text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded transition-colors"
          title="New page in this notebook"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
        </button>
        )}
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto py-1">
        {currentTree.children.map((child) => (
          <TreeItem
            key={child.id}
            node={child}
            depth={0}
            selectedId={currentPageId}
            onSelect={selectPage}
            collapsedState={collapsedState}
            toggleCollapse={toggleCollapse}
            onContextMenu={readOnly ? undefined : handleContextMenu}
          />
        ))}
        {currentTree.children.length === 0 && (
          <p className="p-4 text-sm text-gray-400 italic">No pages yet.</p>
        )}
      </div>

      {/* Context menu */}
      {contextMenu && (
        <div
          className="fixed bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50 min-w-[160px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            onClick={() => {
              setNewPageParent({
                id: contextMenu.node.id,
                title: contextMenu.node.title,
                roles: contextMenu.node.roles,
              });
              setContextMenu(null);
            }}
            className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            + Add child page
          </button>
          {/* Reorder within siblings */}
          {contextMenu.siblings.findIndex((s) => s.id === contextMenu.nodeId) > 0 && (
            <button
              onClick={() => handleMoveInTree(contextMenu.nodeId, contextMenu.siblings, "up")}
              className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
            >
              ↑ Move up
            </button>
          )}
          {contextMenu.siblings.findIndex((s) => s.id === contextMenu.nodeId) < contextMenu.siblings.length - 1 && (
            <button
              onClick={() => handleMoveInTree(contextMenu.nodeId, contextMenu.siblings, "down")}
              className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
            >
              ↓ Move down
            </button>
          )}
          <button
            onClick={() => {
              setDeleteTarget({
                id: contextMenu.node.id,
                title: contextMenu.node.title,
                childCount: countDescendants(contextMenu.node),
              });
              setContextMenu(null);
            }}
            className="w-full text-left px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      )}

      {/* Modals */}
      {newPageParent && (
        <NewPageModal
          parentId={newPageParent.id}
          parentTitle={newPageParent.title}
          parentRoles={newPageParent.roles}
          onClose={() => setNewPageParent(null)}
          onCreated={handleRefresh}
        />
      )}
      {deleteTarget && (
        <DeleteModal
          nodeId={deleteTarget.id}
          nodeTitle={deleteTarget.title}
          childCount={deleteTarget.childCount}
          onClose={() => setDeleteTarget(null)}
          onDeleted={async () => {
            await refreshTree();
            if (currentPageId === deleteTarget.id) {
              refreshPage();
            }
          }}
        />
      )}
    </div>
  );
}
