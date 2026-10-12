import { useEffect, useRef } from 'react';
import StatusMessage from '../atoms/StatusMessage';
import Spinner from '../atoms/Spinner';
import MessageBubble from '../molecules/MessageBubble';
import ChatInput, { type ChatPrefill } from '../molecules/ChatInput';
import type { AskOptions, ChatEngine, ChatMessage, ChatVariant, GoldenQuestion } from '../../services/api';

const HEADER: Record<ChatVariant, { eyebrow: string; title: string; lede: string; empty: string }> = {
  chatbot: {
    eyebrow: 'AirFiber support',
    title: 'How can we help today?',
    lede:
      'Ask about AirFiber plans, bills, refunds, installation or a connection problem, or about a ' +
      'support ticket. Answers come from the help centre and the ticket system, and say where they came from.',
    empty:
      'Type your question below, or pick one on the left. For a ticket, give its id (like TCK-4471) ' +
      'or describe it ("the relocation complaint").',
  },
  admin: {
    eyebrow: 'Admin console',
    title: 'Ask the assistant or the RAG pipeline',
    lede:
      'Pick what answers each question: the MCP assistant customers use (help centre + ticket ' +
      'history), Week 4 hybrid retrieval, or Week 3 dense retrieval. Every message is labelled with ' +
      'how it was answered, so one conversation can compare them.',
    empty:
      'Pick a common question on the left or type your own. Ticket questions need the Assistant; ' +
      'use Compare on the Week 3 vs Week 4 pair to see dense retrieval refuse what hybrid answers.',
  },
  week3: {
    eyebrow: 'Week 3 · baseline RAG',
    title: 'Dense retrieval, grounded answers',
    lede:
      'The notebook pipeline: chunk, embed with MiniLM, search FAISS by cosine, answer with Groq ' +
      'from the retrieved chunks only. Below the score threshold the question is refused before ' +
      'the model is called.',
    empty:
      'Pick one of the golden questions below, or ask your own. Narrow the search with the ' +
      'product-area and top-k controls.',
  },
  week9: {
    eyebrow: 'Week 9 · MCP agent',
    title: 'Help centre + ticket history over MCP',
    lede:
      'The same assistant customers use. The agent discovers its tools from the MCP servers listed ' +
      'on the left and decides which to call; every answer shows each tools/call with its server.',
    empty:
      'Try a ticket question ("Has anyone called back the customer on TCK-4471?"), a ticket without ' +
      'its id ("the relocation complaint"), or a help-centre question.',
  },
  week4: {
    eyebrow: 'Week 4 · hybrid retrieval',
    title: 'Compare Week 3 and Week 4 retrieval',
    lede:
      'Switch between Week 3 (dense vectors only) and Week 4 (BM25 + dense fused with RRF, then ' +
      'cross-encoder reranking) to compare what each one puts in front of the model.',
    empty:
      'G13 and G14 in the golden set are refused under Week 3 and answered under Week 4 - ask one, ' +
      'flip the toggle, and ask again.',
  },
};

type ChatWindowProps = {
  messages: ChatMessage[];
  loading: boolean;
  error: string | null;
  onSend: (text: string, options: AskOptions) => void;
  canAsk: boolean;
  productAreas: string[];
  documents: string[];
  goldenQuestions: GoldenQuestion[];
  defaultTopK: number;
  hybridAvailable: boolean;
  rerankerAvailable: boolean;
  variant?: ChatVariant;
  /** Admin home only - see ChatInput. */
  engine?: ChatEngine;
  onEngineChange?: (engine: ChatEngine) => void;
  prefill?: ChatPrefill | null;
};

export default function ChatWindow({
  messages,
  loading,
  error,
  onSend,
  canAsk,
  productAreas,
  documents,
  goldenQuestions,
  defaultTopK,
  hybridAvailable,
  rerankerAvailable,
  variant = 'week4',
  engine,
  onEngineChange,
  prefill,
}: ChatWindowProps) {
  const copy = HEADER[variant];
  const isChatbot = variant === 'chatbot';
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list) {
      return;
    }
    list.scrollTop = list.scrollHeight;
  }, [messages, loading]);

  return (
    <section
      className={`chat-window ${isChatbot ? 'chat-window--chatbot' : ''} ${variant === 'admin' ? 'chat-window--admin' : ''}`}
    >
      <header className="chat-header">
        <p className="eyebrow">{copy.eyebrow}</p>
        <h1>{copy.title}</h1>
        <p className="lede">{copy.lede}</p>
      </header>
      <div className="message-list" aria-live="polite" ref={listRef}>
        {messages.length === 0 && !loading ? (
          <div className="empty-chat">{copy.empty}</div>
        ) : null}
        {messages.map((message, index) => {
          // Only the latest answer offers follow-ups; they ask again with the
          // same engine and filters that answer was produced with.
          const askable = index === messages.length - 1 && !loading && canAsk && message.options;
          return (
            <MessageBubble
              key={message.id}
              message={message}
              technical={!isChatbot}
              onFollowUp={askable ? (question) => onSend(question, message.options!) : undefined}
            />
          );
        })}
        {loading ? (
          <div className="typing-indicator">
            <Spinner size="sm" label="Generating answer" />
            <span>
              {variant === 'week9' || (variant === 'admin' && engine === 'assistant')
                ? 'Agent is calling MCP tools…'
                : isChatbot
                  ? 'Checking the help centre and tickets…'
                  : 'Retrieving chunks and generating an answer…'}
            </span>
          </div>
        ) : null}
      </div>
      <StatusMessage tone="error">{error}</StatusMessage>
      {!canAsk ? (
        <StatusMessage tone="info">
          {isChatbot
            ? 'The help centre is empty right now. An admin needs to upload articles before questions can be answered.'
            : variant === 'admin'
              ? 'Nothing is indexed yet. Upload documents for RAG answers, or switch to the Assistant for ticket questions.'
              : 'Upload and index documents before chatting.'}
        </StatusMessage>
      ) : null}
      <ChatInput
        onSend={onSend}
        disabled={loading || !canAsk}
        productAreas={productAreas}
        documents={documents}
        goldenQuestions={goldenQuestions}
        defaultTopK={defaultTopK}
        hybridAvailable={hybridAvailable}
        rerankerAvailable={rerankerAvailable}
        variant={variant}
        engine={engine}
        onEngineChange={onEngineChange}
        engineDisabled={loading}
        prefill={prefill}
      />
    </section>
  );
}
