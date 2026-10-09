export type RetrievalMode = 'week3' | 'week4';

/**
 * Which chat a page is. The chatbot always runs the full pipeline with no
 * week-specific controls; the admin Week 3 tab is pinned to dense retrieval;
 * the admin Week 4 tab keeps the toggle and the golden set to compare them.
 */
export type ChatVariant = 'chatbot' | 'week3' | 'week4' | 'week9';

export const VARIANT_MODE: Record<ChatVariant, RetrievalMode> = {
  chatbot: 'week4',
  week3: 'week3',
  week4: 'week4',
  week9: 'week4',
};

/**
 * Variants answered by the MCP assistant (/api/assistant: help centre + ticket
 * history) instead of the RAG-only /api/chat.
 */
export const AGENT_VARIANTS: ChatVariant[] = ['chatbot', 'week9'];

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
  /** Ask the MCP assistant instead of the RAG chat; the retrieval fields are then unused. */
  agent?: boolean;
};

export type ToolCallInfo = {
  server: string;
  tool: string;
  arguments: Record<string, unknown>;
  is_error: boolean;
  latency_ms: number | null;
};

export type AssistantSource = {
  article_id: string;
  source_file: string;
  section: string;
  product_area: string;
  preview: string;
};

export type AssistantResponse = {
  answer: string;
  tool_calls: ToolCallInfo[];
  sources: AssistantSource[];
  tickets: string[];
  stop_reason: string;
  model_turns: number;
  total_tokens: number;
};

export type McpServerInfo = {
  server_name: string;
  server_version: string;
  protocol_version: string;
  transport: string;
  tools: string[];
};

export type McpDiscovery = {
  config: string;
  servers: Record<string, McpServerInfo>;
  tool_count: number;
  tool_names: string[];
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
  /** Set on MCP assistant answers. */
  agent?: {
    toolCalls: ToolCallInfo[];
    sources: AssistantSource[];
    tickets: string[];
    stopReason: string;
    modelTurns: number;
    totalTokens: number;
  };
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

/* ------------------------------------------------------------ Session */

export type Role = 'chatbot' | 'admin';

export type AuthUser = {
  username: string;
  role: Role;
};

export type LoginResponse = {
  token: string;
  expires_at: number;
  user: AuthUser;
};

const TOKEN_KEY = 'ask-my-documents.token';

/** Fired when the backend rejects the stored token, so the app can sign out. */
export const SESSION_EXPIRED_EVENT = 'ask-my-documents:session-expired';

// Storage can be unavailable (private windows, blocked site data). The token
// then lives for this page load only, which is still a working session.
let memoryToken: string | null = null;

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY) ?? memoryToken;
  } catch {
    return memoryToken;
  }
}

export function setToken(token: string | null) {
  memoryToken = token;
  try {
    if (token) {
      window.localStorage.setItem(TOKEN_KEY, token);
    } else {
      window.localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // Kept in memory only.
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    if (response.status === 401 && token && !path.startsWith('/api/auth/login')) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    const error = await readError(response);
    throw new ApiError(error.message, response.status, error.extra);
  }
  return response.json() as Promise<T>;
}

export function login(username: string, password: string, role: Role) {
  return request<LoginResponse>('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role }),
  });
}

export function getCurrentUser() {
  return request<AuthUser>('/api/auth/me');
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

export function sendAssistant(message: string) {
  return request<AssistantResponse>('/api/assistant', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
}

export function getAssistantServers() {
  return request<McpDiscovery>('/api/assistant/servers');
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

/* ---------------------------------------------------------------- Week 7 */

export type Week7MetricSummary = {
  pass_rate: number;
  p50_latency_ms: number;
  total_tokens: number;
  cost_per_ticket_usd: number;
};

export type Week7PerTicket = {
  ticket_id: string;
  system: 'agent' | 'fixed_workflow';
  pass: boolean;
  latency_ms: number;
  total_tokens: number;
  total_cost_usd: number;
  tools_called: string[];
  iterations: number;
  budget_hit: string | null;
  assertions: Record<string, boolean>;
  reply_preview: string;
};

export type Week7ComparisonTable = {
  agent: Week7MetricSummary;
  fixed_workflow: Week7MetricSummary;
  per_ticket: Week7PerTicket[];
};

export type Week7ToolDiff = {
  tool_name: string;
  added_in: string;
  description: string;
  parameters: Record<string, any>;
  non_overlap_note: string;
};

export type Week7BudgetLog = {
  ticket_id?: string;
  budget_hit?: string;
  configured_limit?: number;
  iterations_completed?: number;
  clean_termination?: boolean;
  verdict?: string;
  [key: string]: any;
};

export type Week7Report = {
  available: boolean;
  comparison_table?: Week7ComparisonTable;
  verdict?: string;
  tool_diff?: Week7ToolDiff;
  budget_log?: Week7BudgetLog;
};

export function getWeek7Report() {
  return request<Week7Report>('/api/week7/report');
}

export function triggerWeek7Experiment() {
  return request<{ status: string; message: string }>('/api/week7/run', { method: 'POST' });
}

export function triggerBudgetTest() {
  return request<{ status: string; message: string }>('/api/week7/budget-test', { method: 'POST' });
}

/* ---------------------------------------------------------------- Week 8 */

export type Week8TrajectoryMetrics = {
  tool_choice_accuracy: number;
  argument_validity_rate: number;
  step_efficiency: number;
  cost_per_ticket_usd: {
    mean: number;
    p50: number;
    max: number;
  };
};

export type Week8PriceTag = {
  added_latency_ms: number;
  added_tokens_per_ticket: number;
  added_cost_per_ticket_usd: number;
  flexibility_tradeoff: string;
};

export type Week8Summary = {
  outcome_pass_rate_baseline: number;
  trajectory_pass_rate_baseline: number;
  outcome_vs_trajectory_gap: number;
  top_failure_mode: string;
  top_mode_before: number;
  top_mode_after: number;
  mitigation_applied: string;
  price_tag: Week8PriceTag;
};

export type Week8TicketRun = {
  ticket_id: string;
  category: string;
  accepts_multiple_paths: boolean;
  valid_paths: string[][];
  tools_called: string[];
  steps_taken: number;
  steps_needed: number;
  step_efficiency: number;
  tool_choice_accuracy: number;
  argument_validity_rate: number;
  argument_failures: string[];
  trajectory_passed: boolean;
  outcome_passed: boolean;
  outcome_assertions: Record<string, boolean>;
  is_right_answer_wrong_path: boolean;
  failure_mode: string | null;
  latency_ms: number;
  total_tokens: number;
  total_cost_usd: number;
  reply_preview: string;
};

export type Week8EvalSet = {
  mitigated: boolean;
  total_tickets: number;
  outcome_pass_rate: number;
  trajectory_pass_rate: number;
  outcome_vs_trajectory_gap: number;
  four_trajectory_numbers: Week8TrajectoryMetrics;
  runtime_metrics: {
    latency_p50_ms: number;
    latency_mean_ms: number;
    tokens_mean: number;
  };
  failure_mode_counts: Record<string, number>;
  right_answer_wrong_path_cases: Week8TicketRun[];
  results: Week8TicketRun[];
};

export type Week8RegressionRow = {
  mode: string;
  description: string;
  before_count: number;
  after_count: number;
  delta: number;
  status: string;
};

export type Week8BonusChallenge = {
  attack_payload: string;
  vulnerable_run: {
    reply: string;
    obeyed_attack: boolean;
    latency_ms: number;
    tokens_used: number;
  };
  defended_run: {
    reply: string;
    obeyed_attack: boolean;
    guardrail_passed: boolean;
    guardrail_violations: string[];
    latency_ms: number;
    tokens_used: number;
  };
  defense_price_tag: {
    added_latency_ms: number;
    added_tokens: number;
  };
};

export type Week8Response = {
  available: boolean;
  summary?: Week8Summary;
  baseline_eval?: Week8EvalSet;
  mitigated_eval?: Week8EvalSet;
  named_gap_case?: Week8TicketRun;
  regression_table?: Week8RegressionRow[];
  bonus_challenge?: Week8BonusChallenge;
};

export function getWeek8Results() {
  return request<Week8Response>('/api/week8/results');
}

export function triggerWeek8Experiment() {
  return request<{ status: string; message: string }>('/api/week8/run', { method: 'POST' });
}

export function runWeek8AttackDefense() {
  return request<Week8BonusChallenge>('/api/week8/attack-defense', { method: 'POST' });
}

/* ---------------------------------------------------------------- Week 6 */

export type Week6Result = {
  ticket_id: string;
  week5_mode: string;
  human: number;
  judge: number | null;
  agree: boolean;
  votes?: number[];
  error?: boolean;
  explanation?: string;
};

export type Week6Run = {
  label: string;
  description: string;
  file: string;
  judge: string;
  model: string;
  run_at: string;
  labels_commit: string;
  runs: number;
  agreement_per_run: number[];
  agree: number;
  total: number;
  held_out_agree: number;
  held_out_total: number;
  by_mode: Record<string, { agree: number; total: number }>;
  results: Week6Result[];
};

export type Week6Response = {
  available: boolean;
  few_shot_tickets: string[];
  prediction: string | null;
  runs: Week6Run[];
};

export function getWeek6Results() {
  return request<Week6Response>('/api/week6/results');
}
