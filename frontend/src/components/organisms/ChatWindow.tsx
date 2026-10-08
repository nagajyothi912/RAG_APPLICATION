import { useEffect, useRef } from 'react';
import StatusMessage from '../atoms/StatusMessage';
import Spinner from '../atoms/Spinner';
import MessageBubble from '../molecules/MessageBubble';
import ChatInput from '../molecules/ChatInput';
import type { AskOptions, ChatMessage, ChatVariant, GoldenQuestion } from '../../services/api';

const HEADER: Record<ChatVariant, { eyebrow: string; title: string; lede: string; empty: string }> = {
  chatbot: {
    eyebrow: 'AirFiber support',
    title: 'How can we help today?',
    lede:
      'Answers come only from the AirFiber help centre, with the article each one is from. ' +
      'If the help centre does not cover something, the assistant says so instead of guessing.',
    empty:
      'Ask anything about your AirFiber plan, bill, refund, installation or connection - type your ' +
      'question below, or pick one of the common questions on the left.',
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
    <section className={`chat-window ${isChatbot ? 'chat-window--chatbot' : ''}`}>
      <header className="chat-header">
        <p className="eyebrow">{copy.eyebrow}</p>
        <h1>{copy.title}</h1>
        <p className="lede">{copy.lede}</p>
      </header>
      <div className="message-list" aria-live="polite" ref={listRef}>
        {messages.length === 0 && !loading ? (
          <div className="empty-chat">{copy.empty}</div>
        ) : null}
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} technical={!isChatbot} />
        ))}
        {loading ? (
          <div className="typing-indicator">
            <Spinner size="sm" label="Generating answer" />
            <span>{isChatbot ? 'Looking through the help centre…' : 'Retrieving chunks and generating an answer…'}</span>
          </div>
        ) : null}
      </div>
      <StatusMessage tone="error">{error}</StatusMessage>
      {!canAsk ? (
        <StatusMessage tone="info">
          {isChatbot
            ? 'The help centre is empty right now. An admin needs to upload articles before questions can be answered.'
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
      />
    </section>
  );
}
