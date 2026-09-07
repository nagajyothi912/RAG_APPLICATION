import { useCallback, useState } from 'react';
import { sendChat, type AskOptions, type ChatMessage } from '../services/api';

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = useCallback(
    async (text: string, options: AskOptions) => {
      const content = text.trim();
      if (!content || loading) {
        return;
      }

      const userMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content,
        filter: options.productArea || options.sourceFile || undefined,
        // Snapshot the controls onto the message: the selects keep changing,
        // so scrollback is only readable if each turn records how it was asked.
        options,
      };
      setMessages((current) => [...current, userMessage]);
      setLoading(true);
      setError(null);

      try {
        const result = await sendChat(content, options);
        const assistantMessage: ChatMessage = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: result.answer,
          sources: result.sources || [],
          options,
          retrieval: result.retrieval,
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
