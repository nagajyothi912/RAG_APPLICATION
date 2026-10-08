import { useEffect, useMemo, useState } from 'react';
import { getWeek6Results, type Week6Response, type Week6Run } from '../../services/api';
import Spinner from '../atoms/Spinner';
import StatusMessage from '../atoms/StatusMessage';

const pct = (agree: number, total: number) => (total ? `${((agree / total) * 100).toFixed(1)}%` : '—');

function verdict(value: number | null | undefined) {
  if (value === null || value === undefined) return <span className="w6-verdict is-error">error</span>;
  return value === 1 ? (
    <span className="w6-verdict is-pass">pass</span>
  ) : (
    <span className="w6-verdict is-fail">fail</span>
  );
}

/**
 * Week 6: is the LLM judge's score trustworthy? Read-only view of the committed
 * judge runs against the blind human labels in backend/eval/week6/.
 */
export default function Week6Page() {
  const [data, setData] = useState<Week6Response | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [onlyDisagreements, setOnlyDisagreements] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    getWeek6Results()
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load.'));
  }, []);

  const runs: Week6Run[] = data?.runs ?? [];
  const tickets = useMemo(() => {
    const first = runs[0];
    if (!first) return [];
    return first.results.map((row) => ({
      id: row.ticket_id,
      mode: row.week5_mode,
      human: row.human,
      cells: runs.map((run) => run.results.find((r) => r.ticket_id === row.ticket_id)),
    }));
  }, [runs]);

  const visible = onlyDisagreements
    ? tickets.filter((ticket) => ticket.cells.some((cell) => cell && !cell.agree))
    : tickets;
  const selectedTicket = tickets.find((ticket) => ticket.id === selected);

  return (
    <section className="w6-page">
      <header className="w6-header">
        <h2>Week 6 — Validate the ticket-reply judge</h2>
        <p className="analysis-sub">
          An LLM judge grades support replies pass/fail. Before trusting its number, it is compared
          with blind human labels committed before any judge run. v2 adds few-shot examples taken from
          v1's own disagreements ({data?.few_shot_tickets.join(', ') || '…'}), so the held-out column
          leaves those tickets out.
        </p>
      </header>

      <StatusMessage tone="error">{error}</StatusMessage>
      {!data && !error ? <Spinner label="Loading judge runs" /> : null}
      {data && !data.available ? (
        <StatusMessage tone="info">
          No judge runs found. Run <code>python scripts/evaluate_week6.py</code> from backend/.
        </StatusMessage>
      ) : null}

      {runs.length ? (
        <div className="w6-cards">
          {runs.map((run) => (
            <article key={run.file} className="w6-card">
              <p className="w6-card-label">{run.label}</p>
              <p className="w6-card-value">{pct(run.agree, run.total)}</p>
              <p className="w6-card-detail">
                {run.agree}/{run.total} agree with the human label
              </p>
              <p className="w6-card-detail">
                Held out: {pct(run.held_out_agree, run.held_out_total)} ({run.held_out_agree}/
                {run.held_out_total})
              </p>
              {run.runs > 1 ? (
                <p className="w6-card-detail">Per run: {run.agreement_per_run.join(' · ')}</p>
              ) : null}
              <p className="w6-card-note">{run.description}</p>
            </article>
          ))}
        </div>
      ) : null}

      {data?.prediction ? (
        <blockquote className="w6-prediction">
          <strong>Prediction committed before v2:</strong> {data.prediction}
        </blockquote>
      ) : null}

      {tickets.length ? (
        <>
          <div className="w6-toolbar">
            <h3>Per-ticket verdicts</h3>
            <label className="w6-toggle">
              <input
                type="checkbox"
                checked={onlyDisagreements}
                onChange={(event) => setOnlyDisagreements(event.target.checked)}
              />
              Only disagreements
            </label>
          </div>
          <div className="w6-table-wrap">
            <table className="w6-table">
              <thead>
                <tr>
                  <th>Ticket</th>
                  <th>Week 5 mode</th>
                  <th>Human</th>
                  {runs.map((run) => (
                    <th key={run.file}>{run.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((ticket) => (
                  <tr
                    key={ticket.id}
                    className={selected === ticket.id ? 'is-selected' : undefined}
                    onClick={() => setSelected(selected === ticket.id ? null : ticket.id)}
                  >
                    <td>
                      <strong>{ticket.id}</strong>
                      {data?.few_shot_tickets.includes(ticket.id) ? (
                        <span className="w6-tag">few-shot</span>
                      ) : null}
                    </td>
                    <td>{ticket.mode}</td>
                    <td>{verdict(ticket.human)}</td>
                    {ticket.cells.map((cell, index) => (
                      <td key={runs[index].file} className={cell && !cell.agree ? 'is-disagree' : undefined}>
                        {verdict(cell?.judge)}
                        {cell?.votes && cell.votes.length > 1 ? (
                          <span className="w6-votes">{cell.votes.join('')}</span>
                        ) : null}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selectedTicket ? (
            <div className="w6-detail">
              <h3>{selectedTicket.id} — judge explanations</h3>
              {selectedTicket.cells.map((cell, index) => (
                <p key={runs[index].file}>
                  <strong>{runs[index].label}:</strong> {cell?.explanation || 'No explanation recorded.'}
                </p>
              ))}
            </div>
          ) : (
            <p className="muted-dark">Click a ticket to read each judge's explanation.</p>
          )}
        </>
      ) : null}
    </section>
  );
}
