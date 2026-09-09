import Badge from '../atoms/Badge';
import type { TraceRow } from '../../services/api';

type TraceListProps = {
  rows: TraceRow[];
  total: number;
  offset: number;
  page: number;
  loading: boolean;
  selectedId?: string;
  onOpen: (traceId: string) => void;
  onGoto: (offset: number) => void;
};

/**
 * Tones say "look here", never "this was right". Nothing in a trace establishes
 * correctness - TR-0023 refused and was correct, TR-0112 refused and was wrong,
 * and they look identical to the recorder. So `answered` is neutral rather than
 * green, and the warm tones only mark states worth a second look.
 */
function outcomeLabel(row: TraceRow): { text: string; tone: string } {
  if (row.status === 'error') return { text: 'error', tone: 'error' };
  // The distinction that matters: a gate refusal never reached the model, so
  // the answer the user saw was written by us, not by it.
  if (row.answer_source === 'gate_refusal') return { text: 'refused before LLM', tone: 'warn' };
  if (row.answer_source === 'empty_fallback') return { text: 'empty completion', tone: 'warn' };
  if (row.finish_reason === 'length') return { text: 'hit token cap', tone: 'warn' };
  return { text: 'answered', tone: 'neutral' };
}

export default function TraceList({
  rows,
  total,
  offset,
  page,
  loading,
  selectedId,
  onOpen,
  onGoto,
}: TraceListProps) {
  if (!loading && !rows.length) {
    return <p className="analysis-empty">No traces match these filters.</p>;
  }

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + page, total);

  return (
    <div className={`trace-list${loading ? ' is-loading' : ''}`}>
      <div className="trace-list-head">
        <span>
          {from}–{to} of {total}
        </span>
        <span className="trace-pager">
          <button type="button" disabled={offset <= 0} onClick={() => onGoto(offset - page)}>
            Previous
          </button>
          <button type="button" disabled={to >= total} onClick={() => onGoto(offset + page)}>
            Next
          </button>
        </span>
      </div>

      <ul className="trace-rows">
        {rows.map((row) => {
          const outcome = outcomeLabel(row);
          return (
            <li key={row.trace_id}>
              <button
                type="button"
                className={`trace-row${selectedId === row.trace_id ? ' is-selected' : ''}`}
                onClick={() => onOpen(row.trace_id)}
              >
                <div className="trace-row-top">
                  <code className="trace-id">{row.trace_id}</code>
                  <span className={`pill pill-${outcome.tone}`}>{outcome.text}</span>
                  {row.sampled ? <Badge tone="accent">read</Badge> : null}
                  {row.failure_mode && !row.failure_mode.startsWith('No defect') ? (
                    <Badge>{row.failure_mode}</Badge>
                  ) : null}
                </div>
                <p className="trace-question">{row.question}</p>
                <div className="trace-row-meta">
                  <span>{row.mode}</span>
                  <span>k={row.top_k}</span>
                  {row.filter ? <span title="filter applied">⌗ {row.filter}</span> : null}
                  <span title="best dense cosine vs SCORE_THRESHOLD">
                    gate {row.gate_score?.toFixed(3)} / {row.score_threshold}
                  </span>
                  <span>{row.chunks} chunks</span>
                  {row.latency_ms ? <span>{(row.latency_ms / 1000).toFixed(1)}s</span> : null}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
