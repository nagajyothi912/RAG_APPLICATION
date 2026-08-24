import { useCallback, useState } from 'react';
import { sendChat, type ChatMessage } from '../services/api';

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || loading) {
        return;
      }

      const userMessage: ChatMessage = { id: crypto.randomUUID(), role: 'user', content };
      setMessages((current) => [...current, userMessage]);
      setLoading(true);
      setError(null);

      try {
        const result = await sendChat(content);
        const assistantMessage: ChatMessage = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: result.answer,
          sources: result.sources || [],
        };
        setMessages((current) => [...current, assistantMessage]);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Chat request failed.');
      } finally {
        setLoading(false);
      }
    },
    [loading],
  );

  return { messages, loading, error, send };
}
