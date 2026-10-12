import { useCallback, useEffect, useRef, useState } from 'react';
import { sendAssistant, sendChat, type AskOptions, type ChatMessage, type ChatTurn } from '../services/api';

/**
 * How many earlier messages go back with each question so a follow-up ("and
 * the 3M one?") can be understood. The backend caps this too; see
 * docs/follow_up_questions.md.
 */
const HISTORY_MESSAGES = 6;

function historyOf(messages: ChatMessage[]): ChatTurn[] {
  return messages
    .filter((message) => message.content.trim())
    .slice(-HISTORY_MESSAGES)
    .map((message) => ({ role: message.role, content: message.content }));
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // Read at send time without making `send` change on every message.
  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);
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
      const history = historyOf(messagesRef.current);
      setMessages((current) => [...current, userMessage]);
      setLoading(true);
      setError(null);

      try {
        if (options.agent) {
          const result = await sendAssistant(content, history);
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
              followUps: result.follow_ups ?? [],
            },
          ]);
          return;
        }
        const result = await sendChat(content, options, history);
        const assistantMessage: ChatMessage = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: result.answer,
          sources: result.sources || [],
          options,
          retrieval: result.retrieval,
          rewrittenQuestion: result.rewritten_question || undefined,
          followUps: result.follow_ups ?? [],
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
