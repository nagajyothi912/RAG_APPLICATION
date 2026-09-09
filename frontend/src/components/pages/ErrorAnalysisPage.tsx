import { useEffect, useRef } from 'react';
import { useErrorAnalysis } from '../../hooks/useErrorAnalysis';
import StatusMessage from '../atoms/StatusMessage';
import Spinner from '../atoms/Spinner';
import TaxonomyTable from '../molecules/TaxonomyTable';
import TraceFiltersBar from '../molecules/TraceFilters';
import TraceList from '../molecules/TraceList';
import TraceDetailPanel from '../organisms/TraceDetailPanel';

type ErrorAnalysisPageProps = {
  active: boolean;
  /** From the URL hash, e.g. #analysis/TR-0055, so a trace is shareable. */
  initialTraceId?: string;
};

export default function ErrorAnalysisPage({ active, initialTraceId }: ErrorAnalysisPageProps) {
  const analysis = useErrorAnalysis(active);
  const { summary } = analysis;
  const opened = useRef<string | null>(null);

  // Open the linked trace once. Re-opening on every render would fight the user
  // clicking a different row.
  useEffect(() => {
    if (initialTraceId && opened.current !== initialTraceId) {
      opened.current = initialTraceId;
      void analysis.open(initialTraceId);
    }
  }, [initialTraceId, analysis]);

  return (
    <section className="analysis-page">
      <header className="analysis-header">
        <div>
          <h2>Error analysis</h2>
          <p className="analysis-sub">
            The traces the taxonomy was built from, and everything each one recorded. Read-only.
          </p>
        </div>
        {summary?.available ? (
          <dl className="analysis-stats">
            <div>
              <dt>Traces</dt>
              <dd>{summary.traces}</dd>
            </div>
            <div>
              <dt>Read by hand</dt>
              <dd>{summary.coded}</dd>
            </div>
            <div>
              <dt>Sample seed</dt>
              <dd>{summary.sample_seed ?? '—'}</dd>
            </div>
            <div>
              <dt>Corpus</dt>
              <dd title="Fingerprint of the indexed chunks">
                <code>{summary.corpus_fingerprint || '—'}</code>
              </dd>
            </div>
            <div>
              <dt>Prompt</dt>
              <dd>
                <code>{summary.prompt_id || '—'}</code>
              </dd>
            </div>
          </dl>
        ) : null}
      </header>

      {analysis.error ? <StatusMessage tone="error">{analysis.error}</StatusMessage> : null}

      {summary && !summary.available ? (
        <StatusMessage tone="info">
          No traces found for this source. The analysed run lives in{' '}
          <code>docs/week5/traces.jsonl</code>; the live file is whatever <code>TRACE_PATH</code>{' '}
          points at, and is only written when <code>TRACE_ENABLED=true</code>.
        </StatusMessage>
      ) : null}

      {summary?.available ? (
        <TaxonomyTable
          summary={summary}
          activeMode={analysis.filters.failureMode}
          onPickMode={(mode) => analysis.setFilters({ failureMode: mode })}
        />
      ) : null}

      <TraceFiltersBar
        filters={analysis.filters}
        summary={summary}
        activeCount={analysis.activeFilterCount}
        onChange={analysis.setFilters}
        onClear={analysis.clearFilters}
      />

      <div className="analysis-body">
        <div className="analysis-list">
          {analysis.loading && !analysis.rows.length ? (
            <Spinner label="Loading traces" />
          ) : (
            <TraceList
              rows={analysis.rows}
              total={analysis.total}
              offset={analysis.offset}
              page={analysis.page}
              loading={analysis.loading}
              selectedId={analysis.selected?.trace.trace_id}
              onOpen={(id) => {
                window.location.hash = `analysis/${id}`;
                void analysis.open(id);
              }}
              onGoto={analysis.goto}
            />
          )}
        </div>
        <TraceDetailPanel
          detail={analysis.selected}
          loading={analysis.detailLoading}
          onClose={analysis.close}
        />
      </div>
    </section>
  );
}
