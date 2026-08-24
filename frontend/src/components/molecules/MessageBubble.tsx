import type { ChatMessage } from '../../services/api';

type MessageBubbleProps = {
  message: ChatMessage;
};

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <article className={`message-bubble ${isUser ? 'message-user' : 'message-assistant'}`}>
      <span className="message-role">{isUser ? 'You' : 'Assistant'}</span>
      <p className="message-content">{message.content}</p>
    </article>
  );
}
