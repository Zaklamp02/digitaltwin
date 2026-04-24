import { useState, useCallback, useRef, useEffect } from "react";
import { useCreateBlockNote } from "@blocknote/react";
import { BlockNoteView } from "@blocknote/mantine";
import "@blocknote/mantine/style.css";
import { NodeDetail, apiFetch } from "./KnowledgeContext";

export default function PageEditor({
  page,
  onSaved,
}: {
  page: NodeDetail;
  onSaved: () => void;
}) {
  const [saveStatus, setSaveStatus] = useState<"saved" | "saving" | "error">("saved");
  const saveTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestContent = useRef<{ markdown: string; blocks: unknown } | null>(null);
  const metadataRef = useRef(page.metadata);
  metadataRef.current = page.metadata;

  const editor = useCreateBlockNote({
    initialContent: (page.metadata.body_blocks as any) || undefined,
  });

  // If no body_blocks, parse markdown after editor view is mounted
  useEffect(() => {
    if (!page.metadata.body_blocks && page.body) {
      // requestAnimationFrame ensures BlockNote's ProseMirror view is mounted
      const frame = requestAnimationFrame(() => {
        try {
          const blocks = editor.tryParseMarkdownToBlocks(page.body);
          editor.replaceBlocks(editor.document, blocks);
        } catch (e) {
          console.error("Failed to parse markdown into BlockNote:", e);
        }
      });
      return () => cancelAnimationFrame(frame);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const doSave = useCallback(async () => {
    if (!latestContent.current) return;
    const { markdown, blocks } = latestContent.current;
    setSaveStatus("saving");
    try {
      await apiFetch(`/nodes/${page.id}`, {
        method: "PUT",
        body: JSON.stringify({
          body: markdown,
          metadata: { ...metadataRef.current, body_blocks: blocks },
        }),
      });
      setSaveStatus("saved");
      onSaved();
    } catch {
      setSaveStatus("error");
    }
  }, [page.id, onSaved]);

  const handleChange = useCallback(() => {
    const blocks = editor.document;
    const markdown = editor.blocksToMarkdownLossy(blocks);
    latestContent.current = { markdown, blocks };
    setSaveStatus("saving");

    if (saveTimeout.current) clearTimeout(saveTimeout.current);
    saveTimeout.current = setTimeout(doSave, 800);
  }, [editor, doSave]);

  // Force save on Cmd+S
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        doSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [doSave]);

  return (
    <div>
      {/* Save status indicator */}
      <div className="flex items-center justify-end mb-2">
        <span className={`text-xs ${
          saveStatus === "saved" ? "text-gray-400" :
          saveStatus === "saving" ? "text-amber-500" :
          "text-red-500"
        }`}>
          {saveStatus === "saved" ? "Saved" :
           saveStatus === "saving" ? "Saving…" :
           "Error saving"}
        </span>
      </div>

      {/* BlockNote editor */}
      <div className="prose prose-sm max-w-none">
        <BlockNoteView
          editor={editor}
          onChange={handleChange}
          theme="light"
        />
      </div>
    </div>
  );
}
