import Badge from '../atoms/Badge';
import type { GoldenQuestion } from '../../services/api';

type CommonQuestionsProps = {
  goldenQuestions: GoldenQuestion[];
  ticketQuestions: string[];
  assistantExamples: string[];
  /** A golden question: fills the box and scopes RAG to its document. */
  onPickGolden: (question: GoldenQuestion) => void;
  /** One of the Week 3 vs Week 4 pair: fills the box, whole corpus, RAG engine. */
  onPickContrast: (question: GoldenQuestion) => void;
  /** A ticket or assistant example: fills the box and switches to the Assistant. */
  onPickAssistant: (question: string) => void;
  /** Asks a contrast question under Week 3 and then Week 4. */
  onCompare: (question: GoldenQuestion) => void;
  disabled: boolean;
  /** RAG questions need something indexed; ticket questions do not. */
  ragAvailable: boolean;
};

/** Golden questions grouped by document, in the order the backend lists them. */
function byDocument(questions: GoldenQuestion[]) {
  const groups = new Map<string, GoldenQuestion[]>();
  for (const question of questions) {
    const bucket = groups.get(question.source_file);
    if (bucket) {
      bucket.push(question);
    } else {
      groups.set(question.source_file, [question]);
    }
  }
  return Array.from(groups.entries());
}

/**
 * The admin home's question shortcuts: every question the Week 3, Week 4,
 * Week 9 and chatbot views offer, in one place. Picking one fills the chat box
 * and sets up the engine it needs; nothing is sent until Send (or Compare).
 */
export default function CommonQuestions({
  goldenQuestions,
  ticketQuestions,
  assistantExamples,
  onPickGolden,
  onPickContrast,
  onPickAssistant,
  onCompare,
  disabled,
  ragAvailable,
}: CommonQuestionsProps) {
  const scoped = goldenQuestions.filter((question) => !question.contrast);
  const contrast = goldenQuestions.filter((question) => question.contrast);
  // Ticket questions and assistant examples overlap; list each text once.
  const examples = assistantExamples.filter((question) => !ticketQuestions.includes(question));

  return (
    <section className="common-questions">
      <header className="section-heading">
        <h2>Common questions</h2>
        <p>Picking one fills the box and sets what answers it. Nothing is sent until you press Send.</p>
      </header>

      {ticketQuestions.length ? (
        <details className="common-group" open>
          <summary>
            Tickets <Badge>Assistant</Badge>
          </summary>
          <ul>
            {ticketQuestions.map((question) => (
              <li key={question}>
                <button type="button" onClick={() => onPickAssistant(question)} disabled={disabled}>
                  {question}
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {examples.length ? (
        <details className="common-group">
          <summary>
            Assistant examples <Badge>Assistant</Badge>
          </summary>
          <ul>
            {examples.map((question) => (
              <li key={question}>
                <button type="button" onClick={() => onPickAssistant(question)} disabled={disabled}>
                  {question}
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {contrast.length ? (
        <details className="common-group" open>
          <summary>
            Week 3 vs Week 4 <Badge>whole corpus</Badge>
          </summary>
          <ul>
            {contrast.map((question) => (
              <li key={question.id} className="common-compare">
                <button
                  type="button"
                  onClick={() => onPickContrast(question)}
                  disabled={disabled || !question.available || !ragAvailable}
                  title={
                    question.contrast_holds
                      ? 'Week 4 answers this; Week 3 refuses it.'
                      : 'Both modes answer this right now: the near-duplicate article that makes dense retrieval miss it is not indexed.'
                  }
                >
                  <span className="common-id">{question.id}</span> {question.question}{' '}
                  {question.contrast_holds ? <Badge tone="accent">week 4 only</Badge> : <Badge>both modes</Badge>}
                </button>
                <button
                  type="button"
                  className="common-compare-btn"
                  onClick={() => onCompare(question)}
                  disabled={disabled || !question.available || !ragAvailable}
                  title="Ask it with Dense RAG, then with Hybrid RAG, at the server's top-k"
                >
                  Compare
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {scoped.length ? (
        <details className="common-group">
          <summary>
            Help centre <Badge>golden set</Badge>
          </summary>
          {byDocument(scoped).map(([document, items]) => (
            <div key={document} className="common-doc">
              <h3>{document}</h3>
              <ul>
                {items.map((question) => (
                  <li key={question.id}>
                    <button
                      type="button"
                      onClick={() => onPickGolden(question)}
                      disabled={disabled || !question.available}
                      title={
                        question.available
                          ? 'With a RAG engine, retrieval is scoped to this document.'
                          : 'The document backing this question is not indexed.'
                      }
                    >
                      <span className="common-id">{question.id}</span> {question.question}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      ) : null}
    </section>
  );
}
