import type { ChatMessage, SourceChunk } from '../../services/api';
import Badge from '../atoms/Badge';
import RichText from '../atoms/RichText';

type MessageBubbleProps = {
  message: ChatMessage;
  /**
   * Admin tabs show how retrieval behaved: mode, top-k, the refusal gate and
   * per-stage scores. The chatbot shows only what a customer needs - the
   * answer and where it came from.
   */
  technical?: boolean;
};

/** "help_centre/billing_faq.md" -> "Billing faq": a readable article name for users. */
function articleName(source: string) {
  const base = source.split('/').pop() ?? source;
  const words = base.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const humanize = (name: string) => {
  const words = name.replace(/[_-]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/**
 * What the MCP assistant did to produce this answer. Admins (technical) see each
 * tools/call with its server, arguments, outcome and latency; customers see a
 * short "checked" line and the help articles the answer drew on.
 */
function AgentDetails({ agent, technical }: { agent: NonNullable<ChatMessage['agent']>; technical: boolean }) {
  const checked = Array.from(
    new Set(
      agent.toolCalls
        .filter((call) => !call.is_error)
        .map((call) => {
          const ticket = typeof call.arguments.ticket_id === 'string' ? ` ${call.arguments.ticket_id}` : '';
          return `${humanize(call.tool)}${ticket}`;
        }),
    ),
  );

  return (
    <div className="agent-details">
      {technical ? (
        <details className="citation-list" open>
          <summary>
            {agent.toolCalls.length} MCP tool call{agent.toolCalls.length === 1 ? '' : 's'} · {agent.modelTurns} model
            turn{agent.modelTurns === 1 ? '' : 's'} · {agent.totalTokens.toLocaleString()} tokens
          </summary>
          <ol className="tool-call-list">
            {agent.toolCalls.map((call, index) => (
              <li key={index} className={call.is_error ? 'is-error' : undefined}>
                <Badge tone="accent">{call.server}</Badge>
                <code>{call.tool}</code>
                <code className="tool-call-args">{JSON.stringify(call.arguments)}</code>
                <span className="tool-call-outcome">
                  {call.is_error ? 'isError' : 'ok'}
                  {call.latency_ms !== null ? ` · ${Math.round(call.latency_ms)} ms` : ''}
                </span>
              </li>
            ))}
          </ol>
          <p className="tool-call-stop">stop: {agent.stopReason}</p>
        </details>
      ) : checked.length ? (
        <div className="agent-checked">
          {checked.map((label) => (
            <Badge key={label}>{label}</Badge>
          ))}
        </div>
      ) : null}

      {agent.sources.length ? (
        <details className="citation-list">
          <summary>
            From {new Set(agent.sources.map((source) => source.article_id)).size} help article
            {new Set(agent.sources.map((source) => source.article_id)).size === 1 ? '' : 's'}
          </summary>
          <ol>
            {agent.sources.map((source, index) => (
              <li key={`${source.article_id}-${index}`} className="citation">
                <div className="citation-head">
                  <strong>{technical ? source.source_file : articleName(source.source_file)}</strong>
                  {source.article_id ? <Badge tone="accent">{source.article_id}</Badge> : null}
                  {source.product_area ? <Badge>{source.product_area}</Badge> : null}
                </div>
                {source.section ? <div className="citation-section">{source.section}</div> : null}
                <p className="citation-preview">{source.preview}…</p>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  );
}

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

export default function MessageBubble({ message, technical = true }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const sources = message.sources ?? [];
  const retrieval = message.retrieval;
  const options = message.options;

  return (
    <article className={`message-bubble ${isUser ? 'message-user' : 'message-assistant'}`}>
      <span className="message-role">{isUser ? 'You' : 'Assistant'}</span>

      {isUser && options && technical && options.agent ? (
        <div className="message-options">
          <Badge tone="accent">Assistant · MCP</Badge>
        </div>
      ) : null}

      {isUser && options && technical && !options.agent ? (
        <div className="message-options">
          <Badge tone="accent">{MODE_LABEL[options.mode] ?? options.mode}</Badge>
          <Badge>top k {options.topK}</Badge>
          {options.sourceFile ? <Badge>{options.sourceFile}</Badge> : null}
          {options.productArea ? <Badge>{options.productArea}</Badge> : null}
        </div>
      ) : null}

      {isUser ? (
        <p className="message-content">{message.content}</p>
      ) : (
        <div className="message-content">
          <RichText text={message.content} />
        </div>
      )}

      {!isUser && retrieval && technical ? (
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
      {!isUser && message.agent ? <AgentDetails agent={message.agent} technical={technical} /> : null}

      {!isUser && sources.length > 0 ? (
        <details className="citation-list">
          <summary>
            {technical
              ? `${sources.length} source${sources.length > 1 ? 's' : ''}`
              : `From ${new Set(sources.map((source) => source.source)).size} help article${
                  new Set(sources.map((source) => source.source)).size > 1 ? 's' : ''
                }`}
          </summary>
          <ol>
            {sources.map((source, index) => {
              const movement = rankMovement(source, index + 1);
              return (
                <li key={`${source.source}-${source.chunk_id}-${index}`} className="citation">
                  <div className="citation-head">
                    <strong>{technical ? source.source : articleName(source.source)}</strong>
                    {source.article_id ? <Badge tone="accent">{source.article_id}</Badge> : null}
                    {source.product_area ? <Badge>{source.product_area}</Badge> : null}
                    {technical ? (
                      <span className="citation-score">chunk #{source.chunk_id}</span>
                    ) : null}
                  </div>
                  {source.section ? <div className="citation-section">{source.section}</div> : null}

                  {technical ? (
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
                  ) : null}

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
