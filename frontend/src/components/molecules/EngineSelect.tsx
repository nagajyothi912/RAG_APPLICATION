import type { ChatEngine } from '../../services/api';

type EngineSelectProps = {
  value: ChatEngine;
  onChange: (engine: ChatEngine) => void;
  disabled?: boolean;
  /** Hybrid still runs without these, just as dense-only - so say so rather than hiding it. */
  hybridAvailable?: boolean;
  rerankerAvailable?: boolean;
};

const ENGINES: { value: ChatEngine; label: string; caption: string }[] = [
  { value: 'assistant', label: 'Assistant', caption: 'MCP · help centre + tickets' },
  { value: 'week4', label: 'Hybrid RAG', caption: 'Week 4 · BM25 + rerank' },
  { value: 'week3', label: 'Dense RAG', caption: 'Week 3 · cosine only' },
];

/**
 * The admin home's "Answer with" control: the one chat stands in for the Week 3,
 * Week 4 and Week 9 labs by switching what answers the next question.
 */
export default function EngineSelect({
  value,
  onChange,
  disabled = false,
  hybridAvailable = true,
  rerankerAvailable = true,
}: EngineSelectProps) {
  const degraded = value === 'week4' && (!hybridAvailable || !rerankerAvailable);

  return (
    <div className="mode-toggle-wrap">
      <span className="control-label" id="chat-engine-label">
        Answer with
      </span>
      <div className="mode-toggle" role="radiogroup" aria-labelledby="chat-engine-label">
        {ENGINES.map((engine) => (
          <button
            key={engine.value}
            type="button"
            role="radio"
            aria-checked={value === engine.value}
            className={`mode-option ${value === engine.value ? 'is-active' : ''}`}
            onClick={() => onChange(engine.value)}
            disabled={disabled}
          >
            <strong>{engine.label}</strong>
            <span>{engine.caption}</span>
          </button>
        ))}
      </div>
      {degraded ? (
        <span className="mode-warning">
          {!hybridAvailable ? 'BM25 missing' : 'Reranker unavailable'} — Hybrid falls back to dense
        </span>
      ) : null}
    </div>
  );
}
