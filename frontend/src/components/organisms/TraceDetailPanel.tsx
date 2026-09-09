import { useState } from 'react';
import Badge from '../atoms/Badge';
import Spinner from '../atoms/Spinner';
import type { TraceDetail } from '../../services/api';

type TraceDetailPanelProps = {
  detail: TraceDetail | null;
  loading: boolean;
  onClose: () => void;
};

type Tab = 'retrieval' | 'prompt' | 'answer' | 'raw';

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === '') return null;
  return (
    <div className="kv">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export default function TraceDetailPanel({ detail, loading, onClose }: TraceDetailPanelProps) {
  const [tab, setTab] = useState<Tab>('retrieval');

  if (loading && !detail) {
    return (
      <aside className="trace-detail">
        <Spinner label="Loading trace" />
      </aside>
    );
  }
  if (!detail) {
    return (
      <aside className="trace-detail trace-detail-empty">
        <p>Select a trace to see what it retrieved, what prompt it sent, and what came back.</p>
      </aside>
    );
  }

  const t = detail.trace;
  const request = t.request || {};
  const retrieval = t.retrieval || {};
  const generation = t.generation || {};
  const answer = t.answer || {};
  const config = t.config || {};
  const chunks: any[] = retrieval.chunks || [];
  const threshold = retrieval.score_threshold;

  return (
    <aside className="trace-detail">
      <header className="trace-detail-head">
        <div>
          <code className="trace-id">{t.trace_id}</code>
          {detail.sampled ? <Badge tone="accent">sampled: {detail.sampled}</Badge> : null}
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>

      <p className="trace-detail-question">{request.question}</p>

      {detail.open_coding ? (
        <blockquote className="open-coding">
          <span className="open-coding-label">Open coding</span>
          {detail.open_coding}
          {detail.failure_mode ? (
            <span className="open-coding-mode">{detail.failure_mode}</span>
          ) : null}
        </blockquote>
      ) : null}

      <dl className="kv-grid">
        <Row label="Mode" value={request.mode_effective} />
        <Row label="top_k" value={request.top_k_effective} />
        <Row label="Filters" value={JSON.stringify(request.filters || {})} />
        <Row label="Outcome" value={t.outcome?.status} />
        <Row
          label="Gate"
          value={`${retrieval.gate_score} vs threshold ${threshold} → ${
            retrieval.refused ? 'refused' : 'passed'
          }`}
        />
        <Row label="Answer from" value={answer.source} />
        <Row label="Chunking" value={`${config.chunk_strategy}/${config.chunk_size}/${config.chunk_overlap}`} />
        <Row label="Corpus" value={config.corpus?.fingerprint} />
        <Row label="Prompt" value={generation.prompt_id} />
        <Row label="Model" value={generation.model} />
      </dl>

      <nav className="trace-tabs">
        {(['retrieval', 'prompt', 'answer', 'raw'] as Tab[]).map((name) => (
          <button
            key={name}
            type="button"
            className={tab === name ? 'is-active' : undefined}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </nav>

      {tab === 'retrieval' ? (
        <div className="trace-chunks">
          {chunks.length === 0 ? <p className="analysis-empty">Nothing was retrieved.</p> : null}
          {chunks.map((chunk) => (
            <article
              key={chunk.chunk_uid}
              className={`chunk${chunk.rank === 1 ? ' is-top' : ''}`}
            >
              <header>
                <span className="chunk-rank">#{chunk.rank}</span>
                <code>{chunk.chunk_uid}</code>
                <span className="chunk-article">{chunk.article_id}</span>
              </header>
              <p className="chunk-section">{chunk.section}</p>
              <div className="chunk-scores">
                <span
                  className={
                    threshold !== undefined && chunk.dense_score < threshold ? 'below' : undefined
                  }
                  title="Dense cosine - the number the refusal gate compares"
                >
                  dense {chunk.dense_score}
                </span>
                {chunk.rerank_score !== null ? <span>rerank {chunk.rerank_score}</span> : null}
                {chunk.keyword_score ? <span>bm25 {chunk.keyword_score}</span> : null}
                <span className="chunk-retriever">{chunk.retriever}</span>
              </div>
              <p className="chunk-preview">{chunk.preview}</p>
            </article>
          ))}
        </div>
      ) : null}

      {tab === 'prompt' ? (
        generation.called ? (
          <div className="trace-prompt">
            <h4>System</h4>
            <pre>{generation.system_prompt}</pre>
            <h4>
              User <span className="muted">({generation.context_chars} chars of context)</span>
            </h4>
            <pre>{generation.user_prompt}</pre>
          </div>
        ) : (
          <p className="analysis-empty">
            The model was never called. Retrieval scored {retrieval.gate_score} against a threshold
            of {threshold}, so the answer below was written by the refusal gate, not by the model.
          </p>
        )
      ) : null}

      {tab === 'answer' ? (
        <div className="trace-answer">
          <h4>What the user saw</h4>
          <pre>{answer.text}</pre>
          {generation.called ? (
            <>
              <h4>
                Raw model output{' '}
                {generation.finish_reason ? (
                  <span className="muted">finish: {generation.finish_reason}</span>
                ) : null}
              </h4>
              <pre>{generation.raw_output}</pre>
              {generation.usage ? (
                <p className="muted">
                  {generation.usage.prompt_tokens} in / {generation.usage.completion_tokens} out
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      {tab === 'raw' ? (
        <pre className="trace-raw">{JSON.stringify(t, null, 2)}</pre>
      ) : null}
    </aside>
  );
}
