/**
 * Admin tab: NL Translations
 *
 * Lists all translatable keys with their English source, Dutch translation,
 * status (manual/auto/stale), and actions (edit, reset, regenerate).
 * Also shows the translation prompt used for LLM auto-translation.
 */
import { useCallback, useEffect, useState } from "react";

interface Translation {
  key: string;
  source_en: string;
  text_nl: string | null;
  is_manual: number;
  stale: number;
  updated_at: string;
}

interface Props {
  token: string;
}

export default function TranslationsTab({ token }: Props) {
  const [translations, setTranslations] = useState<Translation[]>([]);
  const [prompt, setPrompt] = useState("");
  const [promptDirty, setPromptDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [filter, setFilter] = useState<"all" | "ui" | "node" | "chat" | "about">("all");
  const [savingPrompt, setSavingPrompt] = useState(false);

  const headers = { "X-Access-Token": token, "Content-Type": "application/json" };

  const fetchAll = useCallback(() => {
    setLoading(true);
    Promise.all([
      fetch("/api/admin/translations", { headers }).then((r) => r.json()),
      fetch("/api/admin/translations/prompt", { headers }).then((r) => r.json()),
    ])
      .then(([tData, pData]) => {
        setTranslations(tData.translations ?? []);
        setPrompt(pData.prompt ?? "");
        setPromptDirty(false);
      })
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const regenerateAll = async () => {
    setRegenerating(true);
    try {
      const r = await fetch("/api/admin/translations/regenerate", { method: "POST", headers });
      const data = await r.json();
      if (data.ok) fetchAll();
    } finally {
      setRegenerating(false);
    }
  };

  const regenerateSingle = async (key: string) => {
    const r = await fetch(`/api/admin/translations/${encodeURIComponent(key)}/regenerate`, {
      method: "POST",
      headers,
    });
    const data = await r.json();
    if (data.ok) {
      setTranslations((prev) =>
        prev.map((t) => (t.key === key ? { ...t, text_nl: data.text_nl, stale: 0, is_manual: 0 } : t)),
      );
    }
  };

  const saveEdit = async (key: string) => {
    await fetch(`/api/admin/translations/${encodeURIComponent(key)}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify({ text_nl: editValue }),
    });
    setTranslations((prev) =>
      prev.map((t) =>
        t.key === key ? { ...t, text_nl: editValue, is_manual: 1, stale: 0 } : t,
      ),
    );
    setEditingKey(null);
  };

  const resetToAuto = async (key: string) => {
    await fetch(`/api/admin/translations/${encodeURIComponent(key)}/reset`, {
      method: "POST",
      headers,
    });
    setTranslations((prev) =>
      prev.map((t) =>
        t.key === key ? { ...t, is_manual: 0, stale: 1, text_nl: null } : t,
      ),
    );
  };

  const savePrompt = async () => {
    setSavingPrompt(true);
    await fetch("/api/admin/translations/prompt", {
      method: "PUT",
      headers,
      body: JSON.stringify({ prompt }),
    });
    setPromptDirty(false);
    setSavingPrompt(false);
  };

  const filtered = translations.filter((t) => {
    if (filter === "all") return true;
    if (filter === "ui") return t.key.startsWith("ui.");
    if (filter === "node") return t.key.startsWith("node.");
    if (filter === "chat") return t.key.startsWith("chat.");
    if (filter === "about") return t.key.startsWith("about.");
    return true;
  });

  const staleCount = translations.filter((t) => t.stale).length;
  const manualCount = translations.filter((t) => t.is_manual).length;

  if (loading) {
    return <div className="text-gray-400 text-sm py-12 text-center">Loading translations…</div>;
  }

  return (
    <div className="space-y-6">
      {/* Summary bar */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-4 text-sm text-gray-500">
          <span>{translations.length} keys</span>
          <span className="text-emerald-600">{manualCount} manual</span>
          {staleCount > 0 && <span className="text-amber-600">{staleCount} stale</span>}
        </div>
        <button
          onClick={regenerateAll}
          disabled={regenerating || staleCount === 0}
          className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {regenerating ? "Translating…" : `Regenerate ${staleCount} stale`}
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1">
        {(["all", "ui", "about", "chat", "node"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              filter === f
                ? "bg-indigo-100 text-indigo-700"
                : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
            }`}
          >
            {f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1)} ({translations.filter((t) => f === "all" || t.key.startsWith(f + ".")).length})
          </button>
        ))}
      </div>

      {/* Translations table */}
      <div className="border border-gray-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-2.5 font-medium text-gray-500 w-[200px]">Key</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-500">English</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-500">Dutch</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-500 w-[80px]">Status</th>
              <th className="text-right px-4 py-2.5 font-medium text-gray-500 w-[160px]">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map((t) => (
              <tr key={t.key} className="hover:bg-gray-50 transition-colors">
                <td className="px-4 py-2.5 font-mono text-xs text-gray-500 break-all">{t.key}</td>
                <td className="px-4 py-2.5 text-gray-700 max-w-[250px]">
                  <div className="truncate" title={t.source_en}>{t.source_en}</div>
                </td>
                <td className="px-4 py-2.5 max-w-[250px]">
                  {editingKey === t.key ? (
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        className="flex-1 border border-gray-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                        autoFocus
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void saveEdit(t.key);
                          if (e.key === "Escape") setEditingKey(null);
                        }}
                      />
                      <button
                        onClick={() => void saveEdit(t.key)}
                        className="text-xs px-2 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700"
                      >
                        Save
                      </button>
                      <button
                        onClick={() => setEditingKey(null)}
                        className="text-xs px-2 py-1 rounded text-gray-500 hover:text-gray-700"
                      >
                        ✕
                      </button>
                    </div>
                  ) : (
                    <div
                      className={`truncate ${t.text_nl ? "text-gray-700" : "text-gray-300 italic"}`}
                      title={t.text_nl ?? "Not translated"}
                    >
                      {t.text_nl ?? "—"}
                    </div>
                  )}
                </td>
                <td className="px-4 py-2.5">
                  {t.stale ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 border border-amber-200 text-amber-700">
                      stale
                    </span>
                  ) : t.is_manual ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 border border-emerald-200 text-emerald-700">
                      manual
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-sky-50 border border-sky-200 text-sky-700">
                      auto
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      onClick={() => {
                        setEditingKey(t.key);
                        setEditValue(t.text_nl ?? "");
                      }}
                      className="text-xs px-2 py-1 rounded text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => void regenerateSingle(t.key)}
                      className="text-xs px-2 py-1 rounded text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
                    >
                      Regen
                    </button>
                    {t.is_manual ? (
                      <button
                        onClick={() => void resetToAuto(t.key)}
                        className="text-xs px-2 py-1 rounded text-gray-500 hover:text-amber-600 hover:bg-amber-50 transition-colors"
                      >
                        Reset
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Translation prompt */}
      <div className="border border-gray-200 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-700">Translation Prompt</h3>
          <div className="flex items-center gap-2">
            {promptDirty && (
              <span className="text-xs text-amber-600">unsaved changes</span>
            )}
            <button
              onClick={savePrompt}
              disabled={!promptDirty || savingPrompt}
              className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {savingPrompt ? "Saving…" : "Save prompt"}
            </button>
          </div>
        </div>
        <p className="text-xs text-gray-400 mb-2">
          This prompt is sent to the LLM when auto-translating. It provides context about the site to improve translation quality.
        </p>
        <textarea
          value={prompt}
          onChange={(e) => {
            setPrompt(e.target.value);
            setPromptDirty(true);
          }}
          rows={12}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-y"
        />
      </div>
    </div>
  );
}
