import { useEffect, useMemo, useState } from 'react';
import { useDocuments } from '../../hooks/useDocuments';
import { useChat } from '../../hooks/useChat';
import { useGoldenQuestions } from '../../hooks/useGoldenQuestions';
import { AGENT_VARIANTS, getHealth, type ChatVariant, type HealthResponse } from '../../services/api';
import RagLayout from '../templates/RagLayout';
import FileUpload from '../organisms/FileUpload';
import DocumentList from '../organisms/DocumentList';
import HelpSidebar from '../organisms/HelpSidebar';
import McpServersPanel from '../organisms/McpServersPanel';
import ChatWindow from '../organisms/ChatWindow';
import StatusMessage from '../atoms/StatusMessage';
import { ASSISTANT_EXAMPLES, TICKET_QUESTIONS } from '../../data/exampleQuestions';

type RagPageProps = {
  variant: ChatVariant;
  /**
   * Whether this page is the visible tab. Admin tabs stay mounted so chat
   * history survives switching; the library is refetched on becoming visible,
   * because another tab may have uploaded or deleted documents meanwhile.
   */
  active?: boolean;
  /** Bumped by the page header's "New chat" button. */
  resetKey?: number;
};

export default function RagPage({ variant, active = true, resetKey = 0 }: RagPageProps) {
  const documents = useDocuments();
  const chat = useChat();
  // Only the admin Week 3/4 tabs manage documents; the assistant variants
  // (customer chatbot, admin Week 9) answer through MCP instead.
  const canManage = variant === 'week3' || variant === 'week4';
  const isAgent = AGENT_VARIANTS.includes(variant);
  const askAgent = (question: string) =>
    chat.send(question, { mode: 'week4', topK: 5, productArea: null, sourceFile: null, agent: true });
  const { refresh } = documents;
  const { reset } = chat;

  useEffect(() => {
    if (active) {
      void refresh();
    }
  }, [active, refresh]);

  useEffect(() => {
    if (resetKey > 0) {
      reset();
    }
  }, [resetKey, reset]);
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
      wide={!canManage}
      sidebar={
        <>
          {healthError ? (
            <StatusMessage tone="error">
              {canManage ? `Backend unreachable: ${healthError}` : 'The assistant is offline right now. Try again shortly.'}
            </StatusMessage>
          ) : null}
          {variant === 'chatbot' ? (
            <HelpSidebar
              productAreas={documents.productAreas}
              metadata={documents.metadata}
              questions={golden.questions}
              ticketQuestions={TICKET_QUESTIONS}
              disabled={chat.loading}
              onAsk={askAgent}
            />
          ) : null}
          {variant === 'week9' ? (
            <McpServersPanel active={active} examples={ASSISTANT_EXAMPLES} onAsk={askAgent} disabled={chat.loading} />
          ) : null}
          {canManage ? (
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
          ) : null}
          {canManage ? (
            <DocumentList
              documents={documents.documents}
              indexedChunks={documents.indexedChunks}
              metadata={documents.metadata}
              onDelete={documents.removeIndexed}
            />
          ) : null}
        </>
      }
      main={
        <ChatWindow
          messages={chat.messages}
          loading={chat.loading}
          error={chat.error}
          onSend={chat.send}
          canAsk={isAgent || documents.indexedChunks > 0}
          productAreas={documents.productAreas}
          documents={documents.documents}
          goldenQuestions={golden.questions}
          defaultTopK={health?.top_k ?? 5}
          hybridAvailable={health?.hybrid_available ?? true}
          rerankerAvailable={health?.reranker_available ?? true}
          variant={variant}
        />
      }
    />
  );
}
