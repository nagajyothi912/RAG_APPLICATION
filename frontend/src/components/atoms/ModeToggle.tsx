import type { RetrievalMode } from '../../services/api';

type ModeToggleProps = {
  value: RetrievalMode;
  onChange: (mode: RetrievalMode) => void;
  disabled?: boolean;
  /** Week 4 still runs without these, just as dense-only - so say so rather than hiding it. */
  hybridAvailable?: boolean;
  rerankerAvailable?: boolean;
};

const MODES: { value: RetrievalMode; label: string; caption: string }[] = [
  { value: 'week3', label: 'Week 3', caption: 'Dense only' },
  { value: 'week4', label: 'Week 4', caption: 'Hybrid + rerank' },
];

export default function ModeToggle({
  value,
  onChange,
  disabled = false,
  hybridAvailable = true,
  rerankerAvailable = true,
}: ModeToggleProps) {
  const degraded = value === 'week4' && (!hybridAvailable || !rerankerAvailable);

  return (
    <div className="mode-toggle-wrap">
      <span className="control-label" id="retrieval-mode-label">
        Retrieval
      </span>
      <div className="mode-toggle" role="radiogroup" aria-labelledby="retrieval-mode-label">
        {MODES.map((mode) => (
          <button
            key={mode.value}
            type="button"
            role="radio"
            aria-checked={value === mode.value}
            className={`mode-option ${value === mode.value ? 'is-active' : ''}`}
            onClick={() => onChange(mode.value)}
            disabled={disabled}
          >
            <strong>{mode.label}</strong>
            <span>{mode.caption}</span>
          </button>
        ))}
      </div>
      {degraded ? (
        <span className="mode-warning">
          {!hybridAvailable ? 'BM25 missing' : 'Reranker unavailable'} — Week 4 falls back to dense
        </span>
      ) : null}
    </div>
  );
}
