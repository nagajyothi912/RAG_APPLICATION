import type { ChatMessage, SourceChunk } from '../../services/api';
import Badge from '../atoms/Badge';

type MessageBubbleProps = {
  message: ChatMessage;
};

const MODE_LABEL: Record<string, string> = {
  week3: 'Week 3 · dense',
  week4: 'Week 4 · hybrid + rerank',
};

/**
 * Where reranking moved a chunk. "dense #7 → #1" is the whole point of Week 4,
 * and it is invisible unless the original dense rank is shown next to the final
 * position.
 */
function rankMovement(source: SourceChunk, finalPosition: number) {
  if (source.rerank_score === null || source.dense_rank === null) {
    return null;
  }
  if (source.dense_rank === finalPosition) {
    return `dense #${source.dense_rank} · held`;
  }
  const arrow = source.dense_rank > finalPosition ? '↑' : '↓';
  return `dense #${source.dense_rank} → #${finalPosition} ${arrow}`;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const sources = message.sources ?? [];
  const retrieval = message.retrieval;
  const options = message.options;

  return (
    <article className={`message-bubble ${isUser ? 'message-user' : 'message-assistant'}`}>
      <span className="message-role">{isUser ? 'You' : 'Assistant'}</span>

      {isUser && options ? (
        <div className="message-options">
          <Badge tone="accent">{MODE_LABEL[options.mode] ?? options.mode}</Badge>
          <Badge>top k {options.topK}</Badge>
          {options.sourceFile ? <Badge>{options.sourceFile}</Badge> : null}
          {options.productArea ? <Badge>{options.productArea}</Badge> : null}
        </div>
      ) : null}

      <p className="message-content">{message.content}</p>

      {!isUser && retrieval ? (
        <div className="retrieval-summary">
          <Badge tone="accent">{MODE_LABEL[retrieval.mode] ?? retrieval.mode}</Badge>
          {retrieval.mode === 'week4' ? (
            <>
              <Badge>{retrieval.hybrid ? 'BM25 + dense' : 'dense only'}</Badge>
              <Badge>{retrieval.reranked ? 'reranked' : 'rerank unavailable'}</Badge>
            </>
          ) : null}
          <span className="retrieval-gate">
            top cosine {retrieval.gate_score.toFixed(3)} vs threshold{' '}
            {retrieval.score_threshold.toFixed(2)}
            {retrieval.refused ? ' · below threshold, refused before the model' : ''}
          </span>
        </div>
      ) : null}

      {/*
        The citation list is closed by default. It is the evidence for the
        answer, not the answer, and five expanded chunks bury the text they
        support. The summary still reports how many there are, so the reader
        knows evidence exists before deciding to open it.
      */}
      {!isUser && sources.length > 0 ? (
        <details className="citation-list">
          <summary>
            {sources.length} source{sources.length > 1 ? 's' : ''}
          </summary>
          <ol>
            {sources.map((source, index) => {
              const movement = rankMovement(source, index + 1);
              return (
                <li key={`${source.source}-${source.chunk_id}-${index}`} className="citation">
                  <div className="citation-head">
                    <strong>{source.source}</strong>
                    {source.article_id ? <Badge tone="accent">{source.article_id}</Badge> : null}
                    {source.product_area ? <Badge>{source.product_area}</Badge> : null}
                    <span className="citation-score">chunk #{source.chunk_id}</span>
                  </div>
                  {source.section ? <div className="citation-section">{source.section}</div> : null}

                  <div className="citation-scores">
                    <span className="score-pill">
                      <em>dense</em> {source.dense_score.toFixed(3)}
                    </span>
                    {source.rerank_score !== null ? (
                      <>
                        <span className="score-pill">
                          <em>bm25</em>{' '}
                          {source.keyword_score > 0 ? source.keyword_score.toFixed(2) : '—'}
                        </span>
                        <span className="score-pill score-pill-strong">
                          <em>rerank</em> {source.rerank_score.toFixed(2)}
                        </span>
                        <span className="score-pill">{source.retriever}</span>
                      </>
                    ) : null}
                    {movement ? <span className="score-move">{movement}</span> : null}
                  </div>

                  <p className="citation-preview">{source.preview}…</p>
                  {source.last_updated && source.last_updated !== 'unknown' ? (
                    <div className="citation-meta">Last updated {source.last_updated}</div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </details>
      ) : null}
    </article>
  );
}
