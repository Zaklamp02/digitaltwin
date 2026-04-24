import { createContext, useContext, useState, useCallback } from "react";

// ── types ─────────────────────────────────────────────────────────────────────

export interface NotebookSummary {
  id: string;
  title: string;
  icon: string;
  roles: string[];
  page_count: number;
  updated_at: string;
  order: number;
}

export interface TreeNode {
  id: string;
  title: string;
  type: string;
  icon: string;
  roles: string[];
  has_body: boolean;
  updated_at: string;
  children: TreeNode[];
}

export interface EdgeInfo {
  id: string;
  source_id: string;
  target_id: string;
  type: string;
  label: string;
  roles: string[];
  direction: "incoming" | "outgoing";
  other_title: string;
  other_type: string;
}

export interface NodeDetail {
  id: string;
  type: string;
  title: string;
  body: string;
  roles: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  edges: EdgeInfo[];
}

export interface NodeSummary {
  id: string;
  type: string;
  title: string;
  roles: string[];
  body_preview: string;
  updated_at: string;
  created_at: string;
}

// ── constants ─────────────────────────────────────────────────────────────────

export const NODE_TYPES = [
  "person", "job", "project", "skill", "education",
  "community", "document", "opinion", "personal", "faq", "system",
  "notebook",
];

export const EDGE_TYPES = [
  "worked_at", "built", "knows", "studied_at", "member_of",
  "relates_to", "used_in", "describes", "authored",
  "has", "includes", "uses",
];

export const CONTAINMENT_EDGE_TYPES = new Set([
  "has", "includes", "member_of", "studied_at",
]);

export const TYPE_COLORS: Record<string, string> = {
  person:    "bg-indigo-100 text-indigo-800",
  job:       "bg-amber-100 text-amber-800",
  project:   "bg-emerald-100 text-emerald-800",
  skill:     "bg-blue-100 text-blue-800",
  education: "bg-violet-100 text-violet-800",
  community: "bg-cyan-100 text-cyan-800",
  document:  "bg-gray-100 text-gray-700",
  opinion:   "bg-orange-100 text-orange-800",
  personal:  "bg-pink-100 text-pink-800",
  faq:       "bg-lime-100 text-lime-800",
  system:    "bg-red-100 text-red-800",
  notebook:  "bg-indigo-100 text-indigo-800",
};

export const ROLE_COLORS: Record<string, string> = {
  public:   "bg-green-100 text-green-800",
  work:     "bg-blue-100 text-blue-700",
  friends:  "bg-pink-100 text-pink-700",
  personal: "bg-purple-100 text-purple-800",
  // legacy alias kept for any old data
  recruiter: "bg-blue-100 text-blue-700",
};

// ── API helper ────────────────────────────────────────────────────────────────

let _token = "";

export function setKnowledgeToken(token: string) {
  _token = token;
}

export async function apiFetch(path: string, opts?: RequestInit) {
  const res = await fetch(`/api/admin${path}`, {
    ...opts,
    headers: {
      "X-Access-Token": _token,
      "Content-Type": "application/json",
      ...(opts?.headers ?? {}),
    },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

// ── context ───────────────────────────────────────────────────────────────────

interface KnowledgeState {
  notebooks: NotebookSummary[];
  currentNotebookId: string | null;
  currentTree: TreeNode | null;
  currentPageId: string | null;
  currentPage: NodeDetail | null;
  loading: boolean;
  error: string;
  orphanNodes: NodeSummary[];
  loadingOrphans: boolean;
  // actions
  loadNotebooks: () => Promise<void>;
  selectNotebook: (id: string) => void;
  selectPage: (id: string) => void;
  loadPage: (id: string) => Promise<void>;
  refreshTree: () => Promise<void>;
  refreshPage: () => Promise<void>;
  loadOrphans: () => Promise<void>;
  clearPage: () => void;
}

const KnowledgeContext = createContext<KnowledgeState | null>(null);

export function useKnowledge() {
  const ctx = useContext(KnowledgeContext);
  if (!ctx) throw new Error("useKnowledge must be inside KnowledgeProvider");
  return ctx;
}

export function KnowledgeProvider({ children }: { children: React.ReactNode }) {
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [currentNotebookId, setCurrentNotebookId] = useState<string | null>(null);
  const [currentTree, setCurrentTree] = useState<TreeNode | null>(null);
  const [currentPageId, setCurrentPageId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState<NodeDetail | null>(null);
  const [orphanNodes, setOrphanNodes] = useState<NodeSummary[]>([]);
  const [loadingOrphans, setLoadingOrphans] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadNotebooks = useCallback(async () => {
    try {
      const data = await apiFetch("/notebooks");
      setNotebooks(data);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  const loadTree = useCallback(async (notebookId: string) => {
    try {
      const data = await apiFetch(`/notebooks/${notebookId}/tree`);
      setCurrentTree(data);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  const selectNotebook = useCallback((id: string) => {
    setCurrentNotebookId(id);
    setCurrentPageId(null);
    setCurrentPage(null);
    loadTree(id);
  }, [loadTree]);

  const loadPage = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const data = await apiFetch(`/nodes/${id}`);
      setCurrentPage(data);
      setCurrentPageId(id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const selectPage = useCallback((id: string) => {
    loadPage(id);
  }, [loadPage]);

  const refreshTree = useCallback(async () => {
    if (currentNotebookId) {
      await loadTree(currentNotebookId);
    }
    await loadNotebooks();
  }, [currentNotebookId, loadTree, loadNotebooks]);

  const refreshPage = useCallback(async () => {
    if (currentPageId) {
      await loadPage(currentPageId);
    }
  }, [currentPageId, loadPage]);

  const clearPage = useCallback(() => {
    setCurrentPageId(null);
    setCurrentPage(null);
  }, []);

  const loadOrphans = useCallback(async () => {
    setLoadingOrphans(true);
    try {
      const data = await apiFetch("/nodes/orphans");
      setOrphanNodes(data.nodes || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoadingOrphans(false);
    }
  }, []);

  return (
    <KnowledgeContext.Provider
      value={{
        notebooks,
        currentNotebookId,
        currentTree,
        currentPageId,
        currentPage,
        loading,
        error,
        orphanNodes,
        loadingOrphans,
        loadNotebooks,
        selectNotebook,
        selectPage,
        loadPage,
        refreshTree,
        refreshPage,
        loadOrphans,
        clearPage,
      }}
    >
      {children}
    </KnowledgeContext.Provider>
  );
}
