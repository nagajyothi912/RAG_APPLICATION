import type { DocumentMetadata, GoldenQuestion } from '../../services/api';

type HelpSidebarProps = {
  productAreas: string[];
  metadata: DocumentMetadata[];
  questions: GoldenQuestion[];
  onAsk: (question: string) => void;
  disabled: boolean;
  /** Example ticket questions, answered from the ticket-history MCP server. */
  ticketQuestions?: string[];
};

const AREA_LABEL: Record<string, string> = {
  plans: 'Plans and pricing',
  billing: 'Billing, payments and refunds',
  installation: 'Installation and setup',
  troubleshooting: 'Connection problems',
  account: 'Your account',
};

export const areaLabel = (area: string) =>
  AREA_LABEL[area] ?? area.charAt(0).toUpperCase() + area.slice(1).replace(/[_-]/g, ' ');

const MAX_QUESTIONS = 8;

/**
 * The user's sidebar: what the assistant can help with, and questions people
 * commonly ask. It replaces the admin's file library - a customer needs topics,
 * not file names and chunk counts.
 */
export default function HelpSidebar({
  productAreas,
  metadata,
  questions,
  onAsk,
  disabled,
  ticketQuestions = [],
}: HelpSidebarProps) {
  const articlesPerArea = new Map<string, number>();
  for (const row of metadata) {
    articlesPerArea.set(row.product_area, (articlesPerArea.get(row.product_area) ?? 0) + 1);
  }

  const seen = new Set<string>();
  const common = questions
    .filter((question) => question.available && !seen.has(question.question) && seen.add(question.question))
    .slice(0, MAX_QUESTIONS);

  return (
    <div className="help-sidebar">
      <section>
        <header className="section-heading">
          <h2>I can help with</h2>
          <p>Answers come from the AirFiber help centre.</p>
        </header>
        {productAreas.length === 0 ? (
          <p className="muted">The help centre is being set up. Please check back soon.</p>
        ) : (
          <ul className="help-topics">
            {productAreas.map((area) => (
              <li key={area}>
                <span>{areaLabel(area)}</span>
                <span className="help-topic-count">
                  {articlesPerArea.get(area) ?? 0} article{articlesPerArea.get(area) === 1 ? '' : 's'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {ticketQuestions.length ? (
        <section className="help-questions">
          <header className="section-heading">
            <h2>Ticket questions</h2>
            <p>Status, callbacks and escalations of a support ticket.</p>
          </header>
          <ul>
            {ticketQuestions.map((question) => (
              <li key={question}>
                <button type="button" onClick={() => onAsk(question)} disabled={disabled}>
                  {question}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {common.length ? (
        <section className="help-questions">
          <header className="section-heading">
            <h2>Common questions</h2>
            <p>Tap one to ask it.</p>
          </header>
          <ul>
            {common.map((question) => (
              <li key={question.id}>
                <button type="button" onClick={() => onAsk(question.question)} disabled={disabled}>
                  {question.question}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
