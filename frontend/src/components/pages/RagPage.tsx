import { useEffect, useMemo, useState } from 'react';
import { useDocuments } from '../../hooks/useDocuments';
import { useChat } from '../../hooks/useChat';
import { useGoldenQuestions } from '../../hooks/useGoldenQuestions';
import { getHealth, type HealthResponse } from '../../services/api';
import RagLayout from '../templates/RagLayout';
import FileUpload from '../organisms/FileUpload';
import DocumentList from '../organisms/DocumentList';
import ChatWindow from '../organisms/ChatWindow';
import StatusMessage from '../atoms/StatusMessage';

export default function RagPage() {
  const documents = useDocuments();
  const chat = useChat();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  // The golden set is refetched when the document set changes, because each
  // question is only offerable while its document is still indexed.
  const documentsKey = useMemo(() => documents.documents.join('|'), [documents.documents]);
  const golden = useGoldenQuestions(documentsKey);

  useEffect(() => {
    getHealth()
      .then((data) => {
        setHealth(data);
        setHealthError(null);
      })
      .catch((err: unknown) => {
        setHealthError(err instanceof Error ? err.message : 'Backend unreachable.');
      });
  }, []);

  return (
    <RagLayout
      sidebar={
        <>
          {healthError ? (
            <StatusMessage tone="error">Backend unreachable: {healthError}</StatusMessage>
          ) : null}
          <FileUpload
            selectedFiles={documents.selectedFiles}
            status={documents.status}
            error={documents.error}
            skipped={documents.skipped}
            indexedChunks={documents.indexedChunks}
            onFilesChosen={documents.addFiles}
            onRemove={documents.removeFile}
            onClear={documents.clearSelected}
            onUpload={documents.upload}
          />
          <DocumentList
            documents={documents.documents}
            indexedChunks={documents.indexedChunks}
            metadata={documents.metadata}
            onDelete={documents.removeIndexed}
          />
        </>
      }
      main={
        <ChatWindow
          messages={chat.messages}
          loading={chat.loading}
          error={chat.error}
          onSend={chat.send}
          canAsk={documents.indexedChunks > 0}
          productAreas={documents.productAreas}
          documents={documents.documents}
          goldenQuestions={golden.questions}
          defaultTopK={health?.top_k ?? 5}
          hybridAvailable={health?.hybrid_available ?? true}
          rerankerAvailable={health?.reranker_available ?? true}
        />
      }
    />
  );
}
