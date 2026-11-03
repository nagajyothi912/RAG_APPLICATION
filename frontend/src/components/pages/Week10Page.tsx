import { useEffect, useMemo, useState } from 'react';
import RichText from '../atoms/RichText';
import {
  getWeek10Report,
  Week10ArmId,
  Week10ArmSummary,
  Week10Call,
  Week10HopShare,
  Week10MultiRun,
  Week10Report,
  Week10Ticket,
} from '../../services/api';

// Read-only on purpose: there is no "run" button. A race costs ~115k Groq tokens,
// and re-running the squad from a button until it wins is the sunk-cost move the
// brief warns against. The race runs from the CLI; this page shows what it saved.

type TabId = 'race' | 'handoffs' | 'failure' | 'verdict';

const TABS: { id: TabId; label: string }[] = [
  { id: 'race', label: '1. Race table' },
  { id: 'handoffs', label: '2. Hand-offs & multiplier' },
  { id: 'failure', label: '3. Failure injection' },
  { id: 'verdict', label: '4. Verdict & A2A' },
];

const ARM_LABEL: Record<Week10ArmId, string> = { single: 'Single agent', multi: 'Triage squad' };

const secs = (ms: number) => `${(ms / 1000).toFixed(1)} s`;
const int = (n: number) => n.toLocaleString('en-US');
const usd = (n: number) => `$${n.toFixed(6)}`;
const pctOf = (n: number, d: number) => (d ? `${Math.round((n / d) * 100)}%` : '—');

function PassBadge({ run }: { run: { pass: boolean | null; judge_score: number | null; failed_assertions: string[] } }) {
  if (run.pass === null) return <span className="w10-badge">not judged</span>;
  if (run.pass) return <span className="w10-badge w10-badge-pass">✓ PASS</span>;
  const why = [...(run.judge_score ? [] : ['judge']), ...run.failed_assertions];
  return (
    <span className="w10-badge w10-badge-fail" title={why.join(', ')}>
      ✕ FAIL <span className="w10-badge-why">({why.join(', ')})</span>
    </span>
  );
}

type CompareTileProps = {
  title: string;
  single: string;
  multi: string;
  /** Which arm is better on this metric, or null for a tie. */
  better: Week10ArmId | null;
  note?: string;
};

function CompareTile({ title, single, multi, better, note }: CompareTileProps) {
  return (
    <div className="w10-tile">
      <span className="w10-tile-title">{title}</span>
      {(['single', 'multi'] as Week10ArmId[]).map((arm) => (
        <div key={arm} className={`w10-tile-row ${better === arm ? 'is-better' : ''}`}>
          <span className="w10-tile-arm">{ARM_LABEL[arm]}</span>
          <span className="w10-tile-val">{arm === 'single' ? single : multi}</span>
          {better === arm ? <span className="w10-tile-flag">better</span> : null}
        </div>
      ))}
      {note ? <span className="w10-tile-note">{note}</span> : null}
    </div>
  );
}

/** The arm with the lower value (single = a, multi = b). */
function lower(a: number, b: number): Week10ArmId | null {
  return a === b ? null : a < b ? 'single' : 'multi';
}

/** The arm with the higher value (single = a, multi = b). */
function higher(a: number, b: number): Week10ArmId | null {
  return a === b ? null : a > b ? 'single' : 'multi';
}

function RaceTab({ report, selected, onSelect }: { report: Week10Report; selected: string; onSelect: (id: string) => void }) {
  const s = report.arms!.single;
  const m = report.arms!.multi;
  const tickets = report.tickets!;
  const ticket = tickets.find((t) => t.ticket_id === selected) ?? tickets[0];
  const passRate = (a: Week10ArmSummary) => `${a.passes}/${a.judged} (${pctOf(a.passes, a.judged)})`;

  return (
    <section className="w10-section">
      <div className="w10-tiles">
        <CompareTile title="Pass rate" single={passRate(s)} multi={passRate(m)} better={higher(s.passes, m.passes)}
          note="judge_v2 and all four Week 6 assertions" />
        <CompareTile title="p50 latency" single={secs(s.p50_ms)} multi={secs(m.p50_ms)} better={lower(s.p50_ms, m.p50_ms)} />
        <CompareTile title="p99 latency" single={secs(s.p99_ms)} multi={secs(m.p99_ms)} better={lower(s.p99_ms, m.p99_ms)}
          note="n = 10, so this is the slowest ticket" />
        <CompareTile title="Total tokens" single={int(s.total_tokens)} multi={int(m.total_tokens)}
          better={lower(s.total_tokens, m.total_tokens)} note="all 10 tickets, every LLM call" />
        <CompareTile title="Cost per ticket" single={usd(s.cost_per_ticket)} multi={usd(m.cost_per_ticket)}
          better={lower(s.cost_per_ticket, m.cost_per_ticket)} />
      </div>

      <div className="w10-panel">
        <h3>Supporting numbers</h3>
        <div className="w10-table-wrap">
          <table className="w10-table">
            <thead>
              <tr><th /><th>{ARM_LABEL.single}</th><th>{ARM_LABEL.multi}</th></tr>
            </thead>
            <tbody>
              <tr><td>Judge v2 passes alone</td><td>{s.judge_passes}/{s.judged}</td><td>{m.judge_passes}/{m.judged}</td></tr>
              <tr><td>All four assertions pass</td><td>{s.assertion_passes}/{s.judged}</td><td>{m.assertion_passes}/{m.judged}</td></tr>
              <tr><td>p50 / p99 with Groq 429 waits removed</td>
                <td>{secs(s.p50_net_ms)} / {secs(s.p99_net_ms)}</td><td>{secs(m.p50_net_ms)} / {secs(m.p99_net_ms)}</td></tr>
              <tr><td>LLM calls</td><td>{s.llm_calls}</td><td>{m.llm_calls}</td></tr>
              <tr><td>…rejected by Groq (tokens not reported)</td><td>{s.rejected_calls}</td><td>{m.rejected_calls}</td></tr>
              <tr><td>Prompt / completion tokens</td>
                <td>{int(s.prompt_tokens)} / {int(s.completion_tokens)}</td><td>{int(m.prompt_tokens)} / {int(m.completion_tokens)}</td></tr>
              <tr><td>Total cost, 10 tickets</td><td>{usd(s.cost_total)}</td><td>{usd(m.cost_total)}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="w10-panel">
        <h3>The same 10 Week-6 cases</h3>
        <p className="w10-sub">Click a ticket to compare both replies.</p>
        <div className="w10-table-wrap">
          <table className="w10-table w10-table-click">
            <thead>
              <tr>
                <th>Ticket</th><th>Tier</th>
                <th>Single agent</th><th>Tokens</th><th>Latency</th>
                <th>Triage squad</th><th>Tokens</th><th>Latency</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((t) => (
                <tr key={t.ticket_id} className={t.ticket_id === ticket.ticket_id ? 'is-selected' : ''}
                  onClick={() => onSelect(t.ticket_id)}>
                  <td><strong>{t.ticket_id}</strong></td>
                  <td>{t.tier}</td>
                  <td><PassBadge run={t.single} /></td><td>{int(t.single.total_tokens)}</td><td>{secs(t.single.latency_ms)}</td>
                  <td><PassBadge run={t.multi} /></td><td>{int(t.multi.total_tokens)}</td><td>{secs(t.multi.latency_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <TicketInspector ticket={ticket} />
    </section>
  );
}

function TicketInspector({ ticket }: { ticket: Week10Ticket }) {
  return (
    <div className="w10-panel">
      <h3>{ticket.ticket_id} · {ticket.tier} · {ticket.tenure_days} days{ticket.refund_requested ? ' · refund requested' : ''}</h3>
      <p className="w10-question">“{ticket.question}”</p>
      <details className="w10-details">
        <summary>Policy context both arms retrieved</summary>
        <pre className="w10-pre">{ticket.context}</pre>
      </details>
      <div className="w10-two-col">
        <div className="w10-run">
          <div className="w10-run-head"><strong>{ARM_LABEL.single}</strong> <PassBadge run={ticket.single} /></div>
          <div className="w10-run-meta">
            {int(ticket.single.total_tokens)} tokens · {secs(ticket.single.latency_ms)} · {ticket.single.iterations} loop turns
          </div>
          <div className="w10-run-meta">Tools: {ticket.single.tools_called.join(' → ') || '—'}</div>
          <pre className="w10-reply">{ticket.single.reply || '(empty reply)'}</pre>
          <p className="w10-judge"><strong>Judge:</strong> {ticket.single.judge_explanation || '—'}</p>
        </div>
        <div className="w10-run">
          <div className="w10-run-head"><strong>{ARM_LABEL.multi}</strong> <PassBadge run={ticket.multi} /></div>
          <div className="w10-run-meta">{int(ticket.multi.total_tokens)} tokens · {secs(ticket.multi.latency_ms)}</div>
          <div className="w10-run-meta">
            Triage: {ticket.multi.triage_tools.join(' → ') || '—'}{ticket.multi.escalated ? ' (escalated)' : ''} ·
            Policy: {ticket.multi.policy_tools.join(' → ') || '—'}
          </div>
          <pre className="w10-reply">{ticket.multi.reply || '(empty reply)'}</pre>
          <p className="w10-judge"><strong>Judge:</strong> {ticket.multi.judge_explanation || '—'}</p>
          <details className="w10-details">
            <summary>What the orchestrator sent each worker</summary>
            <p><strong>Triage brief:</strong> {ticket.multi.plan.triage_brief}</p>
            <p><strong>Policy query:</strong> {ticket.multi.plan.policy_query}</p>
          </details>
        </div>
      </div>
    </div>
  );
}

function HopBars({ title, hops, scale }: { title: string; hops: Week10HopShare[]; scale: number }) {
  return (
    <div className="w10-bars">
      <h4>{title}</h4>
      {hops.map((h) => (
        <div key={h.hop} className="w10-bar-row"
          title={`${h.hop}: ${int(h.total)} tokens (${int(h.prompt)} prompt, ${int(h.completion)} completion) over ${h.calls} calls`}>
          <span className="w10-bar-label">{h.hop}</span>
          <span className="w10-bar-track">
            <span className="w10-bar-fill" style={{ width: `${Math.max((h.total / scale) * 100, 0.5)}%` }} />
          </span>
          <span className="w10-bar-value">{int(h.total)} · {Math.round(h.share * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

function CallLog({ calls }: { calls: Week10Call[] }) {
  return (
    <div className="w10-table-wrap">
      <table className="w10-table w10-table-dense">
        <thead>
          <tr><th>#</th><th>Hand-off</th><th>Kind</th><th>Status</th><th>Prompt</th><th>Completion</th><th>Total</th><th>Latency</th></tr>
        </thead>
        <tbody>
          {calls.map((c, i) => (
            <tr key={i} className={c.status !== 'ok' ? 'is-warn' : ''}>
              <td>{i + 1}</td><td>{c.hop}</td><td>{c.kind}</td><td>{c.status}</td>
              <td>{int(c.prompt_tokens)}</td><td>{int(c.completion_tokens)}</td><td><strong>{int(c.total_tokens)}</strong></td>
              <td>{Math.round(c.latency_ms)} ms</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HandoffsTab({ report, selected, onSelect }: { report: Week10Report; selected: string; onSelect: (id: string) => void }) {
  const mult = report.multiplier!;
  const hops = report.hops!;
  // One scale for both arms, so bar lengths compare across them.
  const scale = Math.max(...hops.single.map((h) => h.total), ...hops.multi.map((h) => h.total));
  const ticket = report.tickets!.find((t) => t.ticket_id === selected) ?? report.tickets![0];

  return (
    <section className="w10-section">
      <div className="w10-panel w10-hero">
        <div className="w10-hero-num">
          <span className="w10-hero-val">{mult.counted?.toFixed(1)}×</span>
          <span className="w10-hero-label">context re-send multiplier<br />squad tokens ÷ single-agent tokens</span>
        </div>
        <div className="w10-hero-text">
          <p>{mult.line}</p>
          <p className="w10-sub">
            Groq rejected {report.arms!.multi.rejected_calls} squad calls without reporting their tokens. Estimating each at
            its hand-off's average call size adds ~{int(mult.estimated_rejected_tokens.multi)} tokens, for an estimated{' '}
            <strong>{mult.estimated.toFixed(1)}×</strong>. Either way, below 1: the squad re-sent less, not more.
          </p>
        </div>
      </div>

      <div className="w10-panel">
        <h3>Where the tokens go</h3>
        <p className="w10-sub">All 10 tickets. Both charts use the same scale, so bar lengths compare across the two arms.</p>
        <HopBars title={`${ARM_LABEL.multi}: ${int(mult.multi_tokens)} tokens`} hops={hops.multi} scale={scale} />
        <HopBars title={`${ARM_LABEL.single}: ${int(mult.single_tokens)} tokens`} hops={hops.single} scale={scale} />
        <p className="w10-sub">
          The single agent re-sends its whole growing conversation on every loop turn. Each squad worker starts from a short
          context of its own, and the two run in parallel.
        </p>
      </div>

      <div className="w10-panel">
        <div className="w10-panel-head">
          <h3>Hand-off log for one ticket</h3>
          <select className="w10-select" value={ticket.ticket_id} onChange={(e) => onSelect(e.target.value)}
            aria-label="Ticket">
            {report.tickets!.map((t) => <option key={t.ticket_id} value={t.ticket_id}>{t.ticket_id}</option>)}
          </select>
        </div>
        <h4>{ARM_LABEL.multi} · {int(ticket.multi.total_tokens)} tokens</h4>
        <CallLog calls={ticket.multi.calls} />
        <h4>{ARM_LABEL.single} · {int(ticket.single.total_tokens)} tokens</h4>
        <CallLog calls={ticket.single.calls} />
      </div>
    </section>
  );
}

function attemptsText(run: Week10MultiRun) {
  return run.policy_attempts
    .map((a) => `attempt ${a.attempt}: HTTP ${a.status ?? 'no response'} after ${Math.round(a.elapsed_ms)} ms`)
    .join(' · ');
}

function FailureTab({ report }: { report: Week10Report }) {
  const f = report.failure;
  if (!f) return <div className="w10-panel">No failure run saved yet.</div>;
  return (
    <section className="w10-section">
      <div className="w10-panel">
        <h3>Policy-lookup worker forced to return HTTP 500 on {f.ticket_id}</h3>
        <p className="w10-question">“{f.question}”</p>
        <ol className="w10-steps">
          <li><strong>Policy hand-off:</strong> {attemptsText(f.run)} (one retry allowed).</li>
          <li><strong>Marked degraded:</strong> {f.run.degraded.join(', ') || 'nothing'}.</li>
          <li><strong>Triage still ran:</strong> {f.run.triage_tools.join(' → ')}{f.run.escalated ? ', escalated' : ''}.</li>
          <li><strong>Cost:</strong> {int(f.run.total_tokens)} tokens, {secs(f.run.latency_ms)} (clean run:{' '}
            {int(f.clean_run.total_tokens)} tokens, {secs(f.clean_run.latency_ms)}).</li>
        </ol>
      </div>

      <div className="w10-two-col">
        <div className="w10-panel w10-run">
          <div className="w10-run-head"><strong>Clean run</strong> <PassBadge run={f.clean_run} /></div>
          <pre className="w10-reply">{f.clean_run.reply}</pre>
          <p className="w10-judge"><strong>Judge:</strong> {f.clean_run.judge_explanation}</p>
        </div>
        <div className="w10-panel w10-run w10-run-fail">
          <div className="w10-run-head"><strong>Policy worker down</strong> <PassBadge run={f.run} /></div>
          <pre className="w10-reply">{f.run.reply}</pre>
          <p className="w10-judge"><strong>Judge:</strong> {f.run.judge_explanation}</p>
        </div>
      </div>

      <div className="w10-two-col">
        <div className="w10-panel">
          <h4>What the synthesiser was given</h4>
          <pre className="w10-pre">{f.run.synthesis_context}</pre>
        </div>
        <div className="w10-panel">
          <h4>The policy the worker would have returned</h4>
          <pre className="w10-pre">{f.policy_context}</pre>
        </div>
      </div>

      <div className="w10-panel w10-confirmed">
        <h3>What the orchestrator actually did</h3>
        {f.confirmed ? <RichText text={f.confirmed} /> : <p>Not confirmed by hand yet.</p>}
      </div>
    </section>
  );
}

function markdownSections(text: string) {
  return text.split(/^## /m).map((chunk, i) => {
    if (i === 0) return { title: '', body: chunk.trim() };
    const [title, ...rest] = chunk.split('\n');
    return { title: title.trim(), body: rest.join('\n').trim() };
  }).filter((s) => s.title || s.body);
}

function VerdictTab({ report }: { report: Week10Report }) {
  const sections = useMemo(() => markdownSections(report.a2a_lifecycle ?? ''), [report.a2a_lifecycle]);
  return (
    <section className="w10-section">
      <div className="w10-panel w10-verdict">
        <h3>Verdict</h3>
        {report.verdict ? <RichText text={report.verdict} /> : <p>verdict.md has not been written yet.</p>}
      </div>
      <div className="w10-panel">
        <h3>Bonus: the failed case on the A2A task lifecycle</h3>
        {sections.map((s, i) => (
          <div key={i} className="w10-md-section">
            {s.title ? <h4>{s.title}</h4> : null}
            <RichText text={s.body} />
          </div>
        ))}
      </div>
      {report.agent_card ? (
        <div className="w10-panel">
          <h3>AgentCard the orchestrator would advertise</h3>
          <p className="w10-sub">
            {String(report.agent_card.name)} · skills:{' '}
            {(report.agent_card.skills as { id: string }[] | undefined)?.map((sk) => sk.id).join(', ')} · auth: bearer token
          </p>
          <details className="w10-details">
            <summary>Full agent_card.json</summary>
            <pre className="w10-pre">{JSON.stringify(report.agent_card, null, 2)}</pre>
          </details>
        </div>
      ) : null}
    </section>
  );
}

export default function Week10Page() {
  const [report, setReport] = useState<Week10Report | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabId>('race');
  const [selected, setSelected] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getWeek10Report();
      setReport(data);
      if (data.tickets?.length) setSelected((current) => current || data.tickets![0].ticket_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const meta = report?.meta;

  return (
    <div className="w10-page">
      <div className="w10-container">
        <header className="w10-header">
          <div>
            <div className="w10-chips">
              <span className="w10-chip">M5 — Multi-agent &amp; A2A</span>
              <span className="w10-chip">Week 10</span>
              <span className="w10-chip">Task Set A · Triage squad</span>
            </div>
            <h1 className="w10-title">Race the triage squad against the single agent</h1>
            <p className="w10-subtitle">
              An orchestrator with a triage worker and a policy-lookup worker, against the Week 7 ReAct agent, on the same
              10 Week-6 cases and the same judge.
            </p>
            {meta ? (
              <p className="w10-meta">
                {meta.model} · temperature 0 · judge_v2 + 4 assertions ({meta.judge_repeats} vote) · run{' '}
                {new Date(meta.started_at).toLocaleString()}
                {meta.pricing_per_m ? ` · $${meta.pricing_per_m.input}/M in, $${meta.pricing_per_m.output}/M out` : ''}
              </p>
            ) : null}
          </div>
          <button type="button" className="w10-btn" onClick={load} disabled={loading}>
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </header>

        {error ? <div className="w10-panel w10-error">Could not load the Week 10 report: {error}</div> : null}

        {report && !report.available ? (
          <div className="w10-panel">
            <h3>No race saved yet</h3>
            <p>{report.reason ?? 'Run the race from the backend directory, then refresh:'}</p>
            <pre className="w10-pre">python -m app.services.triage_squad.race</pre>
            <p className="w10-sub">
              The race is deliberately not started from this page: it costs about 115k Groq tokens, and re-running it until
              the squad wins is the mistake the brief warns about.
            </p>
          </div>
        ) : null}

        {report?.available ? (
          <>
            <nav className="w10-tabs" role="tablist">
              {TABS.map((t) => (
                <button key={t.id} type="button" role="tab" aria-selected={tab === t.id}
                  className={`w10-tab ${tab === t.id ? 'is-active' : ''}`} onClick={() => setTab(t.id)}>
                  {t.label}
                </button>
              ))}
            </nav>
            {tab === 'race' ? <RaceTab report={report} selected={selected} onSelect={setSelected} /> : null}
            {tab === 'handoffs' ? <HandoffsTab report={report} selected={selected} onSelect={setSelected} /> : null}
            {tab === 'failure' ? <FailureTab report={report} /> : null}
            {tab === 'verdict' ? <VerdictTab report={report} /> : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
