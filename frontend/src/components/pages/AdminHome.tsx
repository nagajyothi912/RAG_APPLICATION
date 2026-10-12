import { useEffect, useMemo, useState } from 'react';
import { useDocuments } from '../../hooks/useDocuments';
import { useChat } from '../../hooks/useChat';
import { useGoldenQuestions } from '../../hooks/useGoldenQuestions';
import { getHealth, type ChatEngine, type GoldenQuestion, type HealthResponse } from '../../services/api';
import { ASSISTANT_EXAMPLES, TICKET_QUESTIONS } from '../../data/exampleQuestions';
import RagLayout from '../templates/RagLayout';
import FileUpload from '../organisms/FileUpload';
import DocumentList from '../organisms/DocumentList';
import McpServersPanel from '../organisms/McpServersPanel';
import CommonQuestions from '../organisms/CommonQuestions';
import ChatWindow from '../organisms/ChatWindow';
import StatusMessage from '../atoms/StatusMessage';
import type { ChatPrefill } from '../molecules/ChatInput';

type AdminHomeProps = {
  /** Whether the home view is showing; it stays mounted while a lab is open. */
  active?: boolean;
};

/**
 * The admin console's default view: the shared knowledge-base setup (upload,
 * indexed documents, MCP servers, common questions) beside one chat that can
 * ask every question the Week 3, Week 4 and Week 9 labs can, by switching what
 * answers it.
 */
export default function AdminHome({ active = true }: AdminHomeProps) {
  const documents = useDocuments();
  const chat = useChat();
  const [engine, setEngine] = useState<ChatEngine>('assistant');
  const [prefill, setPrefill] = useState<ChatPrefill | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const documentsKey = useMemo(() => documents.documents.join('|'), [documents.documents]);
  const golden = useGoldenQuestions(documentsKey);
  const { refresh } = documents;
  const ragAvailable = documents.indexedChunks > 0;

  useEffect(() => {
    if (active) {
      void refresh();
    }
  }, [active, refresh]);

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

  const fill = (text: string, sourceFile: string | null) =>
    setPrefill((current) => ({ text, sourceFile, nonce: (current?.nonce ?? 0) + 1 }));

  // A golden question keeps the current engine: under RAG it is scoped to its
  // document (as on the Week 3/4 tabs); the Assistant answers it unscoped.
  const pickGolden = (question: GoldenQuestion) => fill(question.question, question.source_file);

  // The contrast pair only shows anything against the whole corpus, and only
  // under RAG - the Assistant has no Week 3/4 split.
  const pickContrast = (question: GoldenQuestion) => {
    if (engine === 'assistant') {
      setEngine('week3');
    }
    fill(question.question, null);
  };

  // Tickets are only reachable through the MCP ticket-history server.
  const pickAssistant = (question: string) => {
    setEngine('assistant');
    fill(question, null);
  };

  // The Week 4 tab's demo in one click. `send` returns once its answer lands,
  // so the two turns arrive in order.
  const compare = async (question: GoldenQuestion) => {
    const base = { topK: health?.top_k ?? 5, productArea: null, sourceFile: null };
    await chat.send(question.question, { ...base, mode: 'week3' });
    await chat.send(question.question, { ...base, mode: 'week4' });
  };

  return (
    <RagLayout
      sidebar={
        <div className="admin-sidebar">
          {healthError ? <StatusMessage tone="error">Backend unreachable: {healthError}</StatusMessage> : null}
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
          <McpServersPanel active={active} />
          <CommonQuestions
            goldenQuestions={golden.questions}
            ticketQuestions={TICKET_QUESTIONS}
            assistantExamples={ASSISTANT_EXAMPLES}
            onPickGolden={pickGolden}
            onPickContrast={pickContrast}
            onPickAssistant={pickAssistant}
            onCompare={(question) => void compare(question)}
            disabled={chat.loading}
            ragAvailable={ragAvailable}
          />
        </div>
      }
      main={
        <ChatWindow
          messages={chat.messages}
          loading={chat.loading}
          error={chat.error}
          onSend={chat.send}
          canAsk={engine === 'assistant' || ragAvailable}
          productAreas={documents.productAreas}
          documents={documents.documents}
          goldenQuestions={golden.questions}
          defaultTopK={health?.top_k ?? 5}
          hybridAvailable={health?.hybrid_available ?? true}
          rerankerAvailable={health?.reranker_available ?? true}
          variant="admin"
          engine={engine}
          onEngineChange={setEngine}
          prefill={prefill}
        />
      }
    />
  );
}
