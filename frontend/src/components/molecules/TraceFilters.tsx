import Select from '../atoms/Select';
import Button from '../atoms/Button';
import type { AnalysisSummary, TraceFilters as Filters } from '../../services/api';

type TraceFiltersProps = {
  filters: Filters;
  summary: AnalysisSummary | null;
  activeCount: number;
  onChange: (patch: Partial<Filters>) => void;
  onClear: () => void;
};

const ANY = '';

export default function TraceFiltersBar({
  filters,
  summary,
  activeCount,
  onChange,
  onClear,
}: TraceFiltersProps) {
  const modeOptions = [
    { value: ANY, label: 'Any failure mode' },
    { value: 'any', label: 'Any mode assigned' },
    ...(summary?.modes || []).map((m) => ({ value: m.name, label: `${m.rank}. ${m.name}` })),
    ...(summary?.residual ? [{ value: summary.residual.name, label: summary.residual.name }] : []),
  ];

  return (
    <div className="trace-filters">
      <label className="filter-search" htmlFor="trace-search">
        <span>Search</span>
        <input
          id="trace-search"
          type="search"
          placeholder="question or answer text"
          value={filters.q || ''}
          onChange={(event) => onChange({ q: event.target.value })}
        />
      </label>

      <Select
        id="trace-source"
        label="Trace file"
        value={filters.source || 'analysis'}
        onChange={(value) => onChange({ source: value })}
        hint="The committed run the write-up describes, or whatever the server is writing now"
        options={[
          { value: 'analysis', label: 'Analysed run (148)' },
          { value: 'live', label: 'Live trace file' },
        ]}
      />

      <Select
        id="trace-pool"
        label="Pool"
        value={filters.pool || ANY}
        onChange={(value) => onChange({ pool: value })}
        options={[
          { value: ANY, label: 'All pools' },
          ...Object.keys(summary?.pools || {}).map((pool) => ({
            value: pool,
            label: `${pool} (${summary?.pools[pool]})`,
          })),
        ]}
      />

      <Select
        id="trace-sampled"
        label="Sampled"
        value={filters.sampled || ANY}
        onChange={(value) => onChange({ sampled: value })}
        hint="Only the traces drawn by the seeded sample were read by hand"
        options={[
          { value: ANY, label: 'All traces' },
          { value: 'any', label: 'Sampled (read)' },
          { value: 'random', label: 'The random 20' },
          { value: 'demo', label: 'The demo 10' },
        ]}
      />

      <Select
        id="trace-status"
        label="Outcome"
        value={filters.status || ANY}
        onChange={(value) => onChange({ status: value })}
        options={[
          { value: ANY, label: 'Any outcome' },
          ...Object.keys(summary?.statuses || {}).map((s) => ({
            value: s,
            label: `${s} (${summary?.statuses[s]})`,
          })),
        ]}
      />

      <Select
        id="trace-mode"
        label="Retrieval"
        value={filters.mode || ANY}
        onChange={(value) => onChange({ mode: value })}
        options={[
          { value: ANY, label: 'Both' },
          { value: 'week4', label: 'week4' },
          { value: 'week3', label: 'week3' },
        ]}
      />

      <Select
        id="trace-failure"
        label="Failure mode"
        value={filters.failureMode || ANY}
        onChange={(value) => onChange({ failureMode: value })}
        options={modeOptions}
      />

      {activeCount > 0 ? (
        <Button variant="ghost" onClick={onClear}>
          Clear {activeCount} filter{activeCount === 1 ? '' : 's'}
        </Button>
      ) : null}
    </div>
  );
}
