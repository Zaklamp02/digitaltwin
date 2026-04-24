import { useEffect } from "react";
import { KnowledgeProvider, setKnowledgeToken, useKnowledge } from "./KnowledgeContext";
import NotebookSidebar from "./NotebookSidebar";
import NotebookTree from "./NotebookTree";
import PageView from "./PageView";

function KnowledgeTabInner({
  initialNodeId,
  onNavigated,
}: {
  initialNodeId?: string | null;
  onNavigated?: () => void;
}) {
  const { selectPage } = useKnowledge();

  // Handle navigation from Graph tab
  useEffect(() => {
    if (initialNodeId) {
      selectPage(initialNodeId);
      onNavigated?.();
    }
  }, [initialNodeId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex h-full min-h-0">
      <NotebookSidebar />
      <NotebookTree />
      <PageView />
    </div>
  );
}

export default function KnowledgeTab({
  token,
  initialNodeId,
  onNavigated,
}: {
  token: string;
  initialNodeId?: string | null;
  onNavigated?: () => void;
}) {
  setKnowledgeToken(token);

  return (
    <KnowledgeProvider>
      <KnowledgeTabInner
        initialNodeId={initialNodeId}
        onNavigated={onNavigated}
      />
    </KnowledgeProvider>
  );
}
