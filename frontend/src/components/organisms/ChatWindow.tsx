import { useEffect, useRef } from 'react';
import StatusMessage from '../atoms/StatusMessage';
import Spinner from '../atoms/Spinner';
import MessageBubble from '../molecules/MessageBubble';
import ChatInput from '../molecules/ChatInput';
import type { ChatMessage } from '../../services/api';

type ChatWindowProps = {
  messages: ChatMessage[];
  loading: boolean;
  error: string | null;
  onSend: (text: string) => void;
  canAsk: boolean;
};

export default function ChatWindow({ messages, loading, error, onSend, canAsk }: ChatWindowProps) {
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
          does not know.
        </p>
      </header>
      <div className="message-list" aria-live="polite" ref={listRef}>
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
      <ChatInput onSend={onSend} disabled={loading || !canAsk} />
    </section>
  );
}
