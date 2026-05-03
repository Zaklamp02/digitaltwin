import { useEffect } from "react";
import { KnowledgeProvider, setKnowledgeToken, useKnowledge } from "./KnowledgeContext";
import NotebookSidebar from "./NotebookSidebar";
import NotebookTree from "./NotebookTree";
import PageView from "./PageView";

function KnowledgeTabInner({
  initialNodeId,
  onNavigated,
  readOnly,
}: {
  initialNodeId?: string | null;
  onNavigated?: () => void;
  readOnly?: boolean;
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
      <NotebookSidebar readOnly={readOnly} />
      <NotebookTree readOnly={readOnly} />
      <PageView readOnly={readOnly} />
    </div>
  );
}

export default function KnowledgeTab({
  token,
  initialNodeId,
  onNavigated,
  readOnly,
}: {
  token: string;
  initialNodeId?: string | null;
  onNavigated?: () => void;
  readOnly?: boolean;
}) {
  setKnowledgeToken(token);

  return (
    <KnowledgeProvider>
      <KnowledgeTabInner
        initialNodeId={initialNodeId}
        onNavigated={onNavigated}
        readOnly={readOnly}
      />
    </KnowledgeProvider>
  );
}
