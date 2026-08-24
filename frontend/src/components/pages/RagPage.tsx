import { useEffect, useState } from 'react';
import { useDocuments } from '../../hooks/useDocuments';
import { useChat } from '../../hooks/useChat';
import { getHealth } from '../../services/api';
import RagLayout from '../templates/RagLayout';
import FileUpload from '../organisms/FileUpload';
import DocumentList from '../organisms/DocumentList';
import ChatWindow from '../organisms/ChatWindow';
import StatusMessage from '../atoms/StatusMessage';

export default function RagPage() {
  const documents = useDocuments();
  const chat = useChat();
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(() => setHealthError(null))
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
        />
      }
    />
  );
}
