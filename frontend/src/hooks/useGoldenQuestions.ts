import { useCallback, useEffect, useState } from 'react';
import { listGoldenQuestions, type GoldenQuestion } from '../services/api';

/**
 * The curated question set, refetched whenever the indexed documents change -
 * each question's `available` flag depends on its document still being indexed.
 */
export function useGoldenQuestions(documentsKey: string) {
  const [questions, setQuestions] = useState<GoldenQuestion[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await listGoldenQuestions();
      setQuestions(data.questions || []);
    } catch {
      // Best-effort: the chat still works without the shortcuts.
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, documentsKey]);

  return { questions, refresh };
}
