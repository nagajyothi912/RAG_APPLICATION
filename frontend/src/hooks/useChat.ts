import { useCallback, useState } from 'react';
import { sendAssistant, sendChat, type AskOptions, type ChatMessage } from '../services/api';

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
        if (options.agent) {
          const result = await sendAssistant(content);
          setMessages((current) => [
            ...current,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: result.answer || 'Sorry, I could not put an answer together. Please try rephrasing.',
              options,
              agent: {
                toolCalls: result.tool_calls,
                sources: result.sources,
                tickets: result.tickets,
                stopReason: result.stop_reason,
                modelTurns: result.model_turns,
                totalTokens: result.total_tokens,
              },
            },
          ]);
          return;
        }
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

  const reset = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  return { messages, loading, error, send, reset };
}
