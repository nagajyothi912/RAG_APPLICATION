import { useEffect, useRef, useState } from 'react';
import {
  getWeek7Report,
  triggerWeek7Experiment,
  triggerBudgetTest,
  Week7Report,
  Week7PerTicket,
} from '../../services/api';

// ─── Utility ────────────────────────────────────────────────────────────────

function pct(v: number) {
  return `${(v * 100).toFixed(0)}%`;
}
function ms(v: number) {
  return `${v.toFixed(0)} ms`;
}
function usd(v: number) {
  return `$${v.toFixed(5)}`;
}

const TOOL_COLORS: Record<string, string> = {
  retrieve_kb_context:   'var(--moss)',
  generate_ticket_reply: 'var(--copper)',
  escalate_ticket:       '#7c3aed',
};

function ToolBadge({ name }: { name: string }) {
  const label = name
    .replace('retrieve_kb_context',   'retrieve')
    .replace('generate_ticket_reply', 'generate')
    .replace('escalate_ticket',       'escalate ★');
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 20,
        fontSize: '0.7rem',
        fontWeight: 700,
        letterSpacing: '0.03em',
        color: '#fff',
        background: TOOL_COLORS[name] ?? 'var(--ink-soft)',
        marginRight: 4,
      }}
    >
      {label}
    </span>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function MetricCard({
  label,
  agentVal,
  wfVal,
  better,
}: {
  label: string;
  agentVal: string;
  wfVal: string;
  better?: 'agent' | 'workflow' | 'equal';
}) {
  const aBetter = better === 'agent';
  const wBetter = better === 'workflow';
  return (
    <div className="w7-metric-card">
      <span className="w7-metric-label">{label}</span>
      <div className="w7-metric-vals">
        <span className={`w7-metric-val ${aBetter ? 'w7-winner' : ''}`}>
          {agentVal}
          {aBetter && <span className="w7-crown">▲</span>}
        </span>
        <span className="w7-metric-vs">vs</span>
        <span className={`w7-metric-val ${wBetter ? 'w7-winner' : ''}`}>
          {wfVal}
          {wBetter && <span className="w7-crown">▲</span>}
        </span>
      </div>
    </div>
  );
}

function TicketRow({
  agent,
  workflow,
  active,
  onClick,
}: {
  agent?: Week7PerTicket;
  workflow?: Week7PerTicket;
  active: boolean;
  onClick: () => void;
}) {
  const tid    = agent?.ticket_id ?? workflow?.ticket_id ?? '';
  const aPass  = agent?.pass;
  const wPass  = workflow?.pass;
  const aTools = agent?.tools_called ?? [];
  const wTools = workflow?.tools_called ?? [];
  const pathVaries =
    JSON.stringify(aTools) !== JSON.stringify(wTools);

  return (
    <tr
      className={`w7-ticket-row${active ? ' w7-ticket-row--active' : ''}${pathVaries ? ' w7-ticket-row--varies' : ''}`}
      onClick={onClick}
    >
      <td className="w7-tid">
        <span className="w7-ticket-id">{tid}</span>
        {pathVaries && <span className="w7-varies-badge">path varies</span>}
      </td>
      <td>
        <span className={`w7-pass ${aPass ? 'w7-pass--ok' : 'w7-pass--fail'}`}>
          {aPass ? '✓' : '✗'}
        </span>
      </td>
      <td>{agent ? ms(agent.latency_ms) : '—'}</td>
      <td>{agent?.total_tokens ?? '—'}</td>
      <td>
        {aTools.map((t) => (
          <ToolBadge key={t} name={t} />
        ))}
      </td>
      <td>
        <span className={`w7-pass ${wPass ? 'w7-pass--ok' : 'w7-pass--fail'}`}>
          {wPass ? '✓' : '✗'}
        </span>
      </td>
      <td>{workflow ? ms(workflow.latency_ms) : '—'}</td>
      <td>{workflow?.total_tokens ?? '—'}</td>
      <td>
        {wTools.map((t) => (
          <ToolBadge key={t} name={t} />
        ))}
      </td>
    </tr>
  );
}

function TicketDetail({ agent, workflow }: { agent?: Week7PerTicket; workflow?: Week7PerTicket }) {
  const row = agent ?? workflow;
  if (!row) return null;
  return (
    <div className="w7-ticket-detail">
      <h4 className="w7-detail-title">Ticket {row.ticket_id} — Detail</h4>
      {agent && (
        <div className="w7-detail-section">
          <span className="w7-detail-sys">Agent</span>
          <p className="w7-detail-reply">{agent.reply_preview}</p>
          <div className="w7-detail-assertions">
            {Object.entries(agent.assertions).map(([k, v]) => (
              <span key={k} className={`w7-assert ${v ? 'w7-assert--ok' : 'w7-assert--fail'}`}>
                {v ? '✓' : '✗'} {k.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
          {agent.budget_hit && (
            <p className="w7-budget-hit">⚡ Budget hit: {agent.budget_hit}</p>
          )}
        </div>
      )}
      {workflow && (
        <div className="w7-detail-section">
          <span className="w7-detail-sys w7-detail-sys--wf">Fixed Workflow</span>
          <p className="w7-detail-reply">{workflow.reply_preview}</p>
          <div className="w7-detail-assertions">
            {Object.entries(workflow.assertions).map(([k, v]) => (
              <span key={k} className={`w7-assert ${v ? 'w7-assert--ok' : 'w7-assert--fail'}`}>
                {v ? '✓' : '✗'} {k.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function BudgetLog({ log }: { log: Record<string, any> }) {
  return (
    <div className="w7-budget-log">
      <h3 className="w7-section-title">⚡ Budget Termination Log</h3>
      <div className="w7-budget-grid">
        <div className="w7-budget-item">
          <span className="w7-budget-key">Ticket running</span>
          <span className="w7-budget-val">{log.ticket_id ?? '—'}</span>
        </div>
        <div className="w7-budget-item">
          <span className="w7-budget-key">Budget reached</span>
          <span className="w7-budget-val w7-budget-name">{log.budget_hit ?? '—'}</span>
        </div>
        <div className="w7-budget-item">
          <span className="w7-budget-key">Configured limit</span>
          <span className="w7-budget-val">{log.configured_limit ?? '—'} iterations</span>
        </div>
        <div className="w7-budget-item">
          <span className="w7-budget-key">Iterations completed</span>
          <span className="w7-budget-val">{log.iterations_completed ?? '—'}</span>
        </div>
        <div className="w7-budget-item">
          <span className="w7-budget-key">Clean termination</span>
          <span className={`w7-budget-val ${log.clean_termination ? 'w7-pass--ok' : 'w7-pass--fail'}`}>
            {log.clean_termination ? '✓ Yes — no exception raised' : '✗ No'}
          </span>
        </div>
      </div>
      {log.verdict && <p className="w7-budget-verdict">{log.verdict}</p>}
    </div>
  );
}

function ToolDiffCard({ diff }: { diff: NonNullable<Week7Report['tool_diff']> }) {
  return (
    <div className="w7-tool-diff">
      <h3 className="w7-section-title">Third Tool: <code>{diff.tool_name}</code> <span className="w7-new-badge">NEW</span></h3>
      <p className="w7-tool-desc">{diff.description}</p>
      <div className="w7-tool-params">
        {Object.entries(diff.parameters).map(([param, info]) => (
          <div key={param} className="w7-param-row">
            <code className="w7-param-name">{param}</code>
            {typeof info === 'object' && info.values ? (
              <span className="w7-param-enum">
                enum: {(info.values as string[]).map((v) => (
                  <span key={v} className="w7-enum-val">{v}</span>
                ))}
              </span>
            ) : (
              <span className="w7-param-type">{String(info)}</span>
            )}
          </div>
        ))}
      </div>
      <p className="w7-overlap-note"><strong>Non-overlap:</strong> {diff.non_overlap_note}</p>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function Week7Page() {
  const [report, setReport]       = useState<Week7Report | null>(null);
  const [loading, setLoading]     = useState(false);
  const [running, setRunning]     = useState(false);
  const [runMsg, setRunMsg]       = useState('');
  const [activeId, setActiveId]   = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'table' | 'budget' | 'tool'>('table');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetch = async () => {
    setLoading(true);
    try {
      const r = await getWeek7Report();
      setReport(r);
    } catch {
      setReport({ available: false });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetch();
  }, []);

  // Poll while experiment is running
  useEffect(() => {
    if (running) {
      pollRef.current = setInterval(async () => {
        const r = await getWeek7Report();
        setReport(r);
        if (r.available) {
          setRunning(false);
          setRunMsg('');
          if (pollRef.current) clearInterval(pollRef.current);
        }
      }, 4000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [running]);

  const handleRun = async () => {
    setRunning(true);
    setRunMsg('');
    try {
      const res = await triggerWeek7Experiment();
      setRunMsg(res.message);
    } catch {
      setRunMsg('Failed to start experiment.');
      setRunning(false);
    }
  };

  const handleBudgetTest = async () => {
    try {
      const res = await triggerBudgetTest();
      setRunMsg(res.message);
      setTimeout(fetch, 5000);
    } catch {
      setRunMsg('Failed to start budget test.');
    }
  };

  // Build per-ticket index
  const perTicket = report?.comparison_table?.per_ticket ?? [];
  const ticketIds = [...new Set(perTicket.map((r) => r.ticket_id))].sort();
  const byId      = (id: string, sys: string) =>
    perTicket.find((r) => r.ticket_id === id && r.system === sys);
  const activeAgent = activeId ? byId(activeId, 'agent')    : undefined;
  const activeWf    = activeId ? byId(activeId, 'fixed_workflow') : undefined;

  const a = report?.comparison_table?.agent;
  const w = report?.comparison_table?.fixed_workflow;

  return (
    <section className="w7-page">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="w7-header">
        <div>
          <h2 className="w7-title">Week 7 — Agent vs Fixed Workflow</h2>
          <p className="w7-subtitle">
            10 test tickets · 3 tools · 4 safety budgets · same model
          </p>
        </div>
        <div className="w7-actions">
          <button
            id="w7-run-btn"
            className="w7-btn w7-btn--primary"
            onClick={handleRun}
            disabled={running}
          >
            {running ? '⏳ Running…' : '▶ Run Experiment'}
          </button>
          <button
            id="w7-budget-btn"
            className="w7-btn"
            onClick={handleBudgetTest}
            disabled={running}
          >
            ⚡ Budget Test
          </button>
          <button id="w7-refresh-btn" className="w7-btn" onClick={fetch} disabled={loading}>
            {loading ? '…' : '↻ Refresh'}
          </button>
        </div>
      </header>

      {runMsg && <p className="w7-run-msg">{runMsg}</p>}

      {/* ── Not-run state ────────────────────────────────────────────────── */}
      {!report?.available && !loading && (
        <div className="w7-empty">
          <p>No experiment results yet.</p>
          <p>Click <strong>▶ Run Experiment</strong> to run both systems on all 10 tickets.</p>
        </div>
      )}

      {report?.available && (
        <>
          {/* ── Metric cards ──────────────────────────────────────────────── */}
          {a && w && (
            <div className="w7-metric-row">
              <div className="w7-metric-system-label">
                <span className="w7-sys-badge w7-sys-badge--agent">Agent</span>
                <span className="w7-sys-badge w7-sys-badge--wf">Fixed Workflow</span>
              </div>
              <MetricCard
                label="Pass Rate"
                agentVal={pct(a.pass_rate)}
                wfVal={pct(w.pass_rate)}
                better={a.pass_rate > w.pass_rate ? 'agent' : a.pass_rate < w.pass_rate ? 'workflow' : 'equal'}
              />
              <MetricCard
                label="P50 Latency"
                agentVal={ms(a.p50_latency_ms)}
                wfVal={ms(w.p50_latency_ms)}
                better={a.p50_latency_ms < w.p50_latency_ms ? 'agent' : a.p50_latency_ms > w.p50_latency_ms ? 'workflow' : 'equal'}
              />
              <MetricCard
                label="Total Tokens"
                agentVal={a.total_tokens.toLocaleString()}
                wfVal={w.total_tokens.toLocaleString()}
                better={a.total_tokens < w.total_tokens ? 'agent' : a.total_tokens > w.total_tokens ? 'workflow' : 'equal'}
              />
              <MetricCard
                label="Cost / Ticket"
                agentVal={usd(a.cost_per_ticket_usd)}
                wfVal={usd(w.cost_per_ticket_usd)}
                better={a.cost_per_ticket_usd < w.cost_per_ticket_usd ? 'agent' : a.cost_per_ticket_usd > w.cost_per_ticket_usd ? 'workflow' : 'equal'}
              />
            </div>
          )}

          {/* ── Sub-tabs ────────────────────────────────────────────────── */}
          <div className="w7-tabs">
            <button
              className={activeTab === 'table' ? 'w7-tab w7-tab--active' : 'w7-tab'}
              onClick={() => setActiveTab('table')}
            >
              Comparison Table
            </button>
            <button
              className={activeTab === 'budget' ? 'w7-tab w7-tab--active' : 'w7-tab'}
              onClick={() => setActiveTab('budget')}
            >
              ⚡ Budget Log
            </button>
            <button
              className={activeTab === 'tool' ? 'w7-tab w7-tab--active' : 'w7-tab'}
              onClick={() => setActiveTab('tool')}
            >
              Third Tool Diff
            </button>
          </div>

          {/* ── Comparison table ──────────────────────────────────────────── */}
          {activeTab === 'table' && (
            <div className="w7-table-panel">
              <div className="w7-split">
                {/* Left: per-ticket table */}
                <div className="w7-left">
                  <table className="w7-table">
                    <thead>
                      <tr>
                        <th>Ticket</th>
                        <th colSpan={4} className="w7-sys-head w7-sys-head--agent">Agent</th>
                        <th colSpan={4} className="w7-sys-head w7-sys-head--wf">Fixed Workflow</th>
                      </tr>
                      <tr>
                        <th />
                        <th>Pass</th><th>ms</th><th>Tokens</th><th>Tools</th>
                        <th>Pass</th><th>ms</th><th>Tokens</th><th>Tools</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ticketIds.map((id) => (
                        <TicketRow
                          key={id}
                          agent={byId(id, 'agent')}
                          workflow={byId(id, 'fixed_workflow')}
                          active={activeId === id}
                          onClick={() => setActiveId(activeId === id ? null : id)}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Right: ticket detail */}
                <div className="w7-right">
                  {activeId
                    ? <TicketDetail agent={activeAgent} workflow={activeWf} />
                    : (
                      <div className="w7-select-hint">
                        <p>← Click a ticket row to see reply previews and assertion detail.</p>
                        <p>Rows marked <span className="w7-varies-badge">path varies</span> show where agent and workflow chose different tool sequences.</p>
                      </div>
                    )}

                  {/* Verdict */}
                  {report.verdict && (
                    <div className="w7-verdict">
                      <h4 className="w7-verdict-title">Final Verdict</h4>
                      <p className="w7-verdict-text">{report.verdict}</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'budget' && (
            <div className="w7-tab-panel">
              {report.budget_log && Object.keys(report.budget_log).length > 0
                ? <BudgetLog log={report.budget_log} />
                : (
                  <div className="w7-empty">
                    <p>No budget termination log yet.</p>
                    <p>Click <strong>⚡ Budget Test</strong> to force a budget to fire and save the log.</p>
                  </div>
                )}
            </div>
          )}

          {activeTab === 'tool' && (
            <div className="w7-tab-panel">
              {report.tool_diff
                ? <ToolDiffCard diff={report.tool_diff} />
                : <p className="w7-empty">Tool diff unavailable.</p>}
            </div>
          )}
        </>
      )}
    </section>
  );
}
