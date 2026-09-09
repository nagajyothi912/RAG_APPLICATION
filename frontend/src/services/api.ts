export type RetrievalMode = 'week3' | 'week4';

export type SourceChunk = {
  source: string;
  chunk_id: number;
  /** Dense cosine in both modes - the number SCORE_THRESHOLD is compared against. */
  score: number;
  preview: string;
  article_id: string;
  product_area: string;
  last_updated: string;
  section: string;
  dense_score: number;
  keyword_score: number;
  fused_score: number;
  /** null in Week 3, and in Week 4 whenever the cross-encoder could not load. */
  rerank_score: number | null;
  dense_rank: number | null;
  keyword_rank: number | null;
  retriever: string;
};

export type RetrievalInfo = {
  mode: RetrievalMode;
  top_k: number;
  hybrid: boolean;
  reranked: boolean;
  gate_score: number;
  score_threshold: number;
  refused: boolean;
};

export type ChatResponse = {
  answer: string;
  sources: SourceChunk[];
  mode: RetrievalMode;
  retrieval: RetrievalInfo;
  /** Present only when backend tracing is on; empty string otherwise. */
  trace_id?: string;
};

export type GoldenQuestion = {
  id: string;
  question: string;
  source_file: string;
  article_id: string;
  product_area: string;
  kind: string;
  /** "week3-miss-week4-hit" for the pair kept to demonstrate the mode toggle; "" otherwise. */
  contrast: string;
  /**
   * Whether the split is real against the corpus currently indexed. The backend
   * re-measures it per request: the near-duplicate article that makes dense
   * retrieval miss can be deleted or never uploaded, and then both modes answer.
   * Never label a question "week 4 only" without this.
   */
  contrast_holds: boolean;
  available: boolean;
};

export type GoldenSetResponse = {
  questions: GoldenQuestion[];
};

/** Everything the chat controls can vary for a single question. */
export type AskOptions = {
  mode: RetrievalMode;
  topK: number;
  productArea: string | null;
  sourceFile: string | null;
};

export type SkippedFile = {
  filename: string;
  reason: string;
};

export type UploadResponse = {
  uploaded: string[];
  skipped: SkippedFile[];
  indexed_chunks: number;
  documents: string[];
};

export type DocumentMetadata = {
  source_file: string;
  article_id: string;
  product_area: string;
  last_updated: string;
  chunks: number;
};

export type DocumentListResponse = {
  documents: string[];
  indexed_chunks: number;
  metadata: DocumentMetadata[];
  product_areas: string[];
};

export type HealthResponse = {
  status: string;
  embedder_ready: boolean;
  llm_configured: boolean;
  indexed_chunks: number;
  chunk_strategy: string;
  chunk_size: number;
  chunk_overlap: number;
  top_k: number;
  score_threshold: number;
  hybrid_available: boolean;
  reranker_available: boolean;
  reranker_loaded: boolean;
  reranker_model: string;
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: SourceChunk[];
  filter?: string;
  /** Echoed onto both bubbles so scrollback stays readable after the controls move on. */
  options?: AskOptions;
  retrieval?: RetrievalInfo;
};

export type UploadStatusKind = 'idle' | 'uploading' | 'success' | 'error';

export class ApiError extends Error {
  status: number;
  extra: { skipped?: SkippedFile[]; message?: string } | null;

  constructor(
    message: string,
    status: number,
    extra: { skipped?: SkippedFile[]; message?: string } | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.extra = extra;
  }
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

async function readError(response: Response) {
  try {
    const data = await response.json();
    const detail = data.detail;
    if (typeof detail === 'string') {
      return { message: detail, extra: null };
    }
    if (detail && typeof detail === 'object') {
      return {
        message: detail.message || 'Request failed.',
        extra: detail,
      };
    }
    return { message: data.message || `Request failed (${response.status})`, extra: data };
  } catch {
    return { message: `Request failed (${response.status} ${response.statusText})`, extra: null };
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const error = await readError(response);
    throw new ApiError(error.message, response.status, error.extra);
  }
  return response.json() as Promise<T>;
}

export function uploadDocuments(files: File[]) {
  const form = new FormData();
  for (const file of files) {
    const relative = file.webkitRelativePath || file.name;
    form.append('files', file, relative);
  }
  return request<UploadResponse>('/api/documents/upload', {
    method: 'POST',
    body: form,
  });
}

export function sendChat(message: string, options: AskOptions) {
  return request<ChatResponse>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      product_area: options.productArea || null,
      source_file: options.sourceFile || null,
      top_k: options.topK,
      mode: options.mode,
    }),
  });
}

export function listGoldenQuestions() {
  return request<GoldenSetResponse>('/api/golden-questions');
}

export function listDocuments() {
  return request<DocumentListResponse>('/api/documents');
}

export function deleteDocument(name: string) {
  return request<DocumentListResponse>(`/api/documents?name=${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export function getHealth() {
  return request<HealthResponse>('/api/health');
}

/* ---------------------------------------------------------------- Week 5 */

export type TaxonomyMode = {
  rank: number;
  name: string;
  count: number;
  percent: number;
  severity: string;
  example_trace_id: string;
};

export type AnalysisSummary = {
  available: boolean;
  source: string;
  traces: number;
  pools: Record<string, number>;
  statuses: Record<string, number>;
  modes: TaxonomyMode[];
  residual: { name: string; count: number; percent: number } | null;
  sample_size: number;
  sample_seed: number | null;
  sampled_random: string[];
  sampled_demo: string[];
  traces_sha256: string;
  corpus_fingerprint: string;
  prompt_id: string;
  coded: number;
};

export type TraceRow = {
  trace_id: string;
  pool: string | null;
  source_id: string | null;
  started_at: string | null;
  question: string;
  mode: string;
  top_k: number | null;
  filter: string | null;
  status: string;
  answer_source: string;
  refused: boolean;
  gate_score: number | null;
  score_threshold: number | null;
  generation_called: boolean;
  finish_reason: string | null;
  chunks: number;
  top_chunk: string | null;
  answer_preview: string;
  latency_ms: number | null;
  sampled: string | null;
  open_coding: string | null;
  failure_mode: string | null;
};

export type TraceListResponse = {
  total: number;
  offset: number;
  limit: number;
  rows: TraceRow[];
};

/** The full trace record. Loosely typed on purpose: the schema is versioned by
 *  the backend and the detail panel renders whatever fields are present. */
export type TraceDetail = {
  trace: Record<string, any>;
  sampled: string | null;
  open_coding: string | null;
  failure_mode: string | null;
};

export type TraceFilters = {
  source?: string;
  q?: string;
  pool?: string;
  mode?: string;
  status?: string;
  sampled?: string;
  failureMode?: string;
  refused?: boolean;
  offset?: number;
  limit?: number;
};

export function getAnalysisSummary(source = 'analysis') {
  return request<AnalysisSummary>(`/api/analysis/summary?source=${encodeURIComponent(source)}`);
}

export function listTraces(filters: TraceFilters = {}) {
  const params = new URLSearchParams();
  const map: Record<string, unknown> = {
    source: filters.source,
    q: filters.q,
    pool: filters.pool,
    mode: filters.mode,
    status: filters.status,
    sampled: filters.sampled,
    failure_mode: filters.failureMode,
    refused: filters.refused,
    offset: filters.offset,
    limit: filters.limit,
  };
  Object.entries(map).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value));
    }
  });
  return request<TraceListResponse>(`/api/analysis/traces?${params.toString()}`);
}

export function getTrace(traceId: string, source = 'analysis') {
  return request<TraceDetail>(
    `/api/analysis/traces/${encodeURIComponent(traceId)}?source=${encodeURIComponent(source)}`,
  );
}
