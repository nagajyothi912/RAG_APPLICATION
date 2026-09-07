import Badge from '../atoms/Badge';
import type { GoldenQuestion } from '../../services/api';

type GoldenQuestionsProps = {
  questions: GoldenQuestion[];
  open: boolean;
  onToggle: () => void;
  /** Picking the already-selected question again unselects its document. */
  onPick: (question: GoldenQuestion) => void;
  disabled: boolean;
  activeId: string | null;
};

const CONTRAST_GROUP = 'Week 3 vs Week 4 (whole corpus)';

/**
 * Group by document so the per-document questions read as "two per file", not a
 * flat list - and lift the contrast pair into a group of its own.
 *
 * They cannot sit under `airfiber_plans.md` with the rest: every other question
 * scopes retrieval to its document when picked, and these two deliberately do
 * not. Filing them under a document would promise a behaviour they don't have.
 */
function groupByDocument(questions: GoldenQuestion[]) {
  const groups = new Map<string, GoldenQuestion[]>();
  for (const question of questions) {
    const key = question.contrast ? CONTRAST_GROUP : question.source_file;
    const bucket = groups.get(key);
    if (bucket) {
      bucket.push(question);
    } else {
      groups.set(key, [question]);
    }
  }
  return Array.from(groups.entries());
}

export default function GoldenQuestions({
  questions,
  open,
  onToggle,
  onPick,
  disabled,
  activeId,
}: GoldenQuestionsProps) {
  if (questions.length === 0) {
    return null;
  }

  const groups = groupByDocument(questions);

  return (
    <div className={`golden-set ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        className="golden-toggle"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls="golden-panel"
      >
        <span className="golden-toggle-icon" aria-hidden="true">
          {open ? '−' : '+'}
        </span>
        Golden set of questions
        <span className="golden-count">{questions.length}</span>
      </button>

      {open ? (
        <div className="golden-panel" id="golden-panel">
          <p className="golden-hint">
            Known-answer questions, two per indexed document. Picking one fills the box and scopes
            retrieval to that document; clicking it again unselects the document. The last group
            searches the whole corpus instead — those two are answered under Week 4 and refused
            under Week 3, so switch the mode toggle to see the difference.
          </p>
          {groups.map(([document, items]) => (
            <section className="golden-group" key={document}>
              <h3 className="golden-group-title">
                {document}
                <Badge tone="accent">
                  {document === CONTRAST_GROUP ? 'no filter' : items[0]?.article_id}
                </Badge>
              </h3>
              <ul className="golden-list">
                {items.map((question) => {
                  const isActive = activeId === question.id;
                  return (
                    <li key={question.id}>
                      <button
                        type="button"
                        className={`golden-item ${isActive ? 'is-active' : ''}`}
                        onClick={() => onPick(question)}
                        disabled={disabled || !question.available}
                        aria-pressed={isActive}
                        title={
                          question.available
                            ? question.contrast
                              ? question.contrast_holds
                                ? 'Searches the whole corpus. Week 4 answers this; Week 3 refuses it.'
                                : 'Both modes answer this right now. The near-duplicate article that makes dense retrieval miss it is not indexed, so there is no split to show.'
                              : isActive
                                ? 'Click again to unselect this document'
                                : undefined
                            : 'The document backing this question is not indexed.'
                        }
                      >
                        <span className="golden-id">{question.id}</span>
                        <span className="golden-question">{question.question}</span>
                        {question.kind === 'table' ? <Badge>table</Badge> : null}
                        {question.contrast ? (
                          question.contrast_holds ? (
                            <Badge tone="accent">week 4 only</Badge>
                          ) : (
                            <Badge>both modes</Badge>
                          )
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      ) : null}
    </div>
  );
}
