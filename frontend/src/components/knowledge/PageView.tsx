import { useState, useRef, useEffect, useCallback } from "react";
import { useKnowledge, TYPE_COLORS, ROLE_COLORS, CONTAINMENT_EDGE_TYPES, EdgeInfo, apiFetch, TreeNode } from "./KnowledgeContext";

// ── Delete Confirmation Modal ─────────────────────────────────────────────────

function DeletePageModal({
  nodeId,
  nodeTitle,
  onClose,
  onDeleted,
}: {
  nodeId: string;
  nodeTitle: string;
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
      setDeleting(false);
    }
  }, [nodeId, onClose, onDeleted]);

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-[380px] p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Delete "{nodeTitle}"?</h3>
        <p className="text-sm text-gray-600 mb-1">This action cannot be undone.</p>
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
import PageEditor from "./PageEditor";
import CrossLinksPanel from "./CrossLinksPanel";

function TypeBadge({ type }: { type: string }) {
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${TYPE_COLORS[type] ?? "bg-gray-100 text-gray-700"}`}>
      {type}
    </span>
  );
}

function RoleBadge({ role }: { role: string }) {
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${ROLE_COLORS[role] ?? "bg-gray-100 text-gray-600"}`}>
      {role}
    </span>
  );
}

// ── Inline title editing ──────────────────────────────────────────────────────

function EditableTitle({ title, pageId, onSaved }: { title: string; pageId: string; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setValue(title); }, [title]);
  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);

  const save = useCallback(async () => {
    setEditing(false);
    const trimmed = value.trim();
    if (!trimmed || trimmed === title) { setValue(title); return; }
    try {
      await apiFetch(`/nodes/${pageId}`, {
        method: "PUT",
        body: JSON.stringify({ title: trimmed }),
      });
      onSaved();
    } catch {
      setValue(title);
    }
  }, [value, title, pageId, onSaved]);

  if (!editing) {
    return (
      <h1
        className="text-2xl font-bold text-gray-900 flex-1 cursor-text hover:bg-gray-50 rounded px-1 -mx-1 transition-colors"
        onClick={() => setEditing(true)}
        title="Click to edit title"
      >
        {title}
      </h1>
    );
  }

  return (
    <input
      ref={inputRef}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === "Enter") save();
        if (e.key === "Escape") { setValue(title); setEditing(false); }
      }}
      className="text-2xl font-bold text-gray-900 flex-1 bg-white border border-indigo-300 rounded px-1 -mx-1 outline-none focus:ring-2 focus:ring-indigo-200"
    />
  );
}

// ── Roles editor popover ──────────────────────────────────────────────────────

const ALL_ROLES = ["public", "work", "friends", "personal"];

function RolesEditor({ roles, pageId, onSaved }: { roles: string[]; pageId: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set(roles));
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => { setSelected(new Set(roles)); }, [roles]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const toggle = useCallback(async (role: string) => {
    const next = new Set(selected);
    if (next.has(role)) next.delete(role); else next.add(role);
    if (next.size === 0) return; // must have at least one role
    setSelected(next);
    try {
      await apiFetch(`/nodes/${pageId}`, {
        method: "PUT",
        body: JSON.stringify({ roles: Array.from(next) }),
      });
      onSaved();
    } catch {
      setSelected(new Set(roles));
    }
  }, [selected, roles, pageId, onSaved]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 hover:opacity-80 transition-opacity"
        title="Edit roles"
      >
        {roles.map((r) => <RoleBadge key={r} role={r} />)}
        <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
        </svg>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg p-2 z-20 min-w-[140px]">
          {ALL_ROLES.map((role) => (
            <label key={role} className="flex items-center gap-2 px-2 py-1.5 hover:bg-gray-50 rounded cursor-pointer">
              <input
                type="checkbox"
                checked={selected.has(role)}
                onChange={() => toggle(role)}
                className="rounded text-indigo-500 focus:ring-indigo-400"
              />
              <RoleBadge role={role} />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Breadcrumb ────────────────────────────────────────────────────────────────

function Breadcrumb({ page }: { page: { id: string; edges: EdgeInfo[] } }) {
  const { selectPage } = useKnowledge();

  const containmentParents = page.edges.filter(
    (e) => e.direction === "incoming" && CONTAINMENT_EDGE_TYPES.has(e.type)
  );

  if (containmentParents.length === 0) return null;

  return (
    <div className="flex items-center gap-1 text-xs text-gray-400 mb-1">
      {containmentParents.map((p, i) => (
        <span key={p.id} className="flex items-center gap-1">
          {i > 0 && <span>›</span>}
          <button
            onClick={() => selectPage(p.source_id === page.id ? p.target_id : p.source_id)}
            className="hover:text-indigo-600 hover:underline"
          >
            {p.other_title}
          </button>
        </span>
      ))}
    </div>
  );
}

// ── Chapter child list ────────────────────────────────────────────────────────

function findTreeNode(tree: TreeNode | null, id: string): TreeNode | null {
  if (!tree) return null;
  if (tree.id === id) return tree;
  for (const child of tree.children) {
    const found = findTreeNode(child, id);
    if (found) return found;
  }
  return null;
}

function ChapterChildList({ children }: { children: TreeNode[] }) {
  const { selectPage } = useKnowledge();

  if (children.length === 0) return null;

  return (
    <div className="mt-8 border-t border-gray-100 pt-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">Pages in this chapter</h3>
      <div className="space-y-1">
        {children.map((child) => (
          <button
            key={child.id}
            onClick={() => selectPage(child.id)}
            className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-50 transition-colors group"
          >
            <span className="text-sm font-medium text-gray-700 group-hover:text-indigo-600 flex-1 truncate">
              {child.title}
            </span>
            <TypeBadge type={child.type} />
            {child.children.length > 0 && (
              <span className="text-[10px] text-gray-400">{child.children.length} sub</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Main PageView ─────────────────────────────────────────────────────────────

export default function PageView() {
  const { currentPage, currentPageId, currentTree, loading, refreshPage, refreshTree, clearPage, loadOrphans } = useKnowledge();
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  if (!currentPageId) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 bg-gray-50">
        <div className="text-center">
          <p className="text-4xl mb-3">📝</p>
          <p className="text-sm">Select a page to view and edit it.</p>
        </div>
      </div>
    );
  }

  if (loading && !currentPage) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400">
        <p className="text-sm">Loading…</p>
      </div>
    );
  }

  if (!currentPage) return null;

  const crossLinks = currentPage.edges.filter(
    (e) => !CONTAINMENT_EDGE_TYPES.has(e.type)
  );

  // Check if this is a chapter (has children in the tree)
  const treeNode = findTreeNode(currentTree, currentPage.id);
  const isChapter = treeNode && treeNode.children.length > 0;

  const handleSaved = () => {
    refreshPage();
    refreshTree();
  };

  const handleDeleted = () => {
    clearPage();
    refreshTree();
    loadOrphans();
  };

  return (
    <div className="flex-1 flex min-w-0 min-h-0">
      {/* Main content area */}
      <div className="flex-1 overflow-y-auto bg-white">
        <div className="max-w-3xl mx-auto px-8 py-6">
          {/* Header */}
          <div className="mb-6">
            <Breadcrumb page={currentPage} />
            <div className="flex items-center gap-2 mb-2">
              <EditableTitle title={currentPage.title} pageId={currentPage.id} onSaved={handleSaved} />
              <TypeBadge type={currentPage.type} />
              <button
                onClick={() => setShowDeleteModal(true)}
                title="Delete this page"
                className="ml-auto p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
            <div className="flex items-center gap-2">
              <RolesEditor roles={currentPage.roles} pageId={currentPage.id} onSaved={handleSaved} />
              <span className="text-xs text-gray-400 ml-2">
                Updated {new Date(currentPage.updated_at).toLocaleDateString("nl-NL")}
              </span>
            </div>
          </div>

          {/* Editor */}
          <PageEditor
            key={currentPageId}
            page={currentPage}
            onSaved={handleSaved}
          />

          {/* Chapter: show child page list below editor */}
          {isChapter && <ChapterChildList children={treeNode.children} />}
        </div>
      </div>

      {/* Cross-links panel — always visible for add capability */}
      <CrossLinksPanel
        edges={crossLinks}
        nodeId={currentPage.id}
        onRefresh={refreshPage}
      />

      {showDeleteModal && (
        <DeletePageModal
          nodeId={currentPage.id}
          nodeTitle={currentPage.title}
          onClose={() => setShowDeleteModal(false)}
          onDeleted={handleDeleted}
        />
      )}
    </div>
  );
}
