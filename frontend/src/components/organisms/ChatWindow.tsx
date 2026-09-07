import { useEffect, useRef } from 'react';
import StatusMessage from '../atoms/StatusMessage';
import Spinner from '../atoms/Spinner';
import MessageBubble from '../molecules/MessageBubble';
import ChatInput from '../molecules/ChatInput';
import type { AskOptions, ChatMessage, GoldenQuestion } from '../../services/api';

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
}: ChatWindowProps) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list) {
      return;
    }
    list.scrollTop = list.scrollHeight;
  }, [messages, loading]);

  return (
    <section className="chat-window">
      <header className="chat-header">
        <p className="eyebrow">Ask my documents</p>
        <h1>Grounded answers, with sources</h1>
        <p className="lede">
          Questions are answered only from indexed files. If the answer is not there, the model says it
          does not know. Switch between Week 3 retrieval (dense vectors only) and Week 4 (BM25 + dense,
          then cross-encoder reranking) to compare what each one puts in front of the model.
        </p>
      </header>
      <div className="message-list" aria-live="polite" ref={listRef}>
        {messages.length === 0 && !loading ? (
          <div className="empty-chat">
            Pick one of the twelve golden questions below, or ask your own. Narrow the search with the
            document, product-area, and top-k controls.
          </div>
        ) : null}
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {loading ? (
          <div className="typing-indicator">
            <Spinner size="sm" label="Generating answer" />
            <span>Retrieving chunks and generating an answer…</span>
          </div>
        ) : null}
      </div>
      <StatusMessage tone="error">{error}</StatusMessage>
      {!canAsk ? (
        <StatusMessage tone="info">Upload and index documents before chatting.</StatusMessage>
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
      />
    </section>
  );
}
