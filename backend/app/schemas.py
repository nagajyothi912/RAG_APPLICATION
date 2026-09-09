from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    product_area: str | None = Field(
        default=None,
        description="Restrict retrieval to chunks whose product_area metadata matches.",
    )
    source_file: str | None = Field(
        default=None,
        description=(
            "Restrict retrieval to a single indexed document. Accepts the relative "
            "path or the bare filename."
        ),
    )
    top_k: int | None = Field(default=None, ge=1, le=20)
    mode: Literal["week3", "week4"] = Field(
        default="week3",
        description=(
            "week3 = dense vector retrieval only (the notebook pipeline). "
            "week4 = BM25 + dense fused with RRF, then cross-encoder reranked."
        ),
    )


class SourceChunk(BaseModel):
    source: str
    chunk_id: int
    # Kept as the dense cosine in both modes so it stays comparable to
    # SCORE_THRESHOLD; the per-stage scores below are what differ by mode.
    score: float
    preview: str
    article_id: str = ""
    product_area: str = ""
    last_updated: str = ""
    section: str = ""
    dense_score: float = 0.0
    keyword_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: float | None = None
    dense_rank: int | None = None
    keyword_rank: int | None = None
    retriever: str = "dense"


class RetrievalInfo(BaseModel):
    mode: str = "week3"
    top_k: int = 0
    hybrid: bool = False
    reranked: bool = False
    gate_score: float = 0.0
    score_threshold: float = 0.0
    refused: bool = False


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    mode: str = "week3"
    retrieval: RetrievalInfo = RetrievalInfo()
    # Returned so a user reporting a bad answer can quote one string that finds
    # the whole trace. Empty when tracing is off, which is the default.
    trace_id: str = ""


class GoldenQuestion(BaseModel):
    id: str
    question: str
    source_file: str
    article_id: str = ""
    product_area: str = ""
    kind: str = "prose"
    # Non-empty ("week3-miss-week4-hit") marks a question kept to demonstrate the
    # retrieval-mode split. The UI leaves these unscoped; see ChatInput.pickGolden.
    contrast: str = ""
    # Measured against the live index, not read off the fixture: True only while
    # dense-only retrieval really does miss this question. The corpus that makes
    # it miss can be deleted or never uploaded, and then the split is not there
    # to demonstrate. See RagService.golden_questions.
    contrast_holds: bool = False
    available: bool = True


class GoldenSetResponse(BaseModel):
    questions: list[GoldenQuestion] = []


class SkippedFile(BaseModel):
    filename: str
    reason: str


class UploadResponse(BaseModel):
    uploaded: list[str]
    skipped: list[SkippedFile]
    indexed_chunks: int
    documents: list[str]


class DocumentMetadata(BaseModel):
    source_file: str
    article_id: str = ""
    product_area: str = ""
    last_updated: str = ""
    chunks: int = 0


class DocumentListResponse(BaseModel):
    documents: list[str]
    indexed_chunks: int
    metadata: list[DocumentMetadata] = []
    product_areas: list[str] = []


class HealthResponse(BaseModel):
    status: str
    embedder_ready: bool
    llm_configured: bool
    indexed_chunks: int
    chunk_strategy: str = ""
    chunk_size: int = 0
    chunk_overlap: int = 0
    top_k: int = 0
    score_threshold: float = 0.0
    hybrid_available: bool = False
    reranker_available: bool = False
    reranker_loaded: bool = False
    reranker_model: str = ""


class TaxonomyMode(BaseModel):
    rank: int
    name: str
    count: int
    percent: float
    severity: str
    example_trace_id: str


class TaxonomyResidual(BaseModel):
    name: str
    count: int
    percent: float


class AnalysisSummary(BaseModel):
    """Everything the Error Analysis header needs, in one call."""

    available: bool
    source: str = "analysis"
    traces: int = 0
    pools: dict[str, int] = {}
    statuses: dict[str, int] = {}
    modes: list[TaxonomyMode] = []
    residual: TaxonomyResidual | None = None
    sample_size: int = 0
    sample_seed: int | None = None
    sampled_random: list[str] = []
    sampled_demo: list[str] = []
    traces_sha256: str = ""
    corpus_fingerprint: str = ""
    prompt_id: str = ""
    coded: int = 0


class TraceRow(BaseModel):
    trace_id: str
    pool: str | None = None
    source_id: str | None = None
    started_at: str | None = None
    question: str
    mode: str = ""
    top_k: int | None = None
    filter: str | None = None
    status: str = ""
    answer_source: str = ""
    refused: bool = False
    gate_score: float | None = None
    score_threshold: float | None = None
    generation_called: bool = False
    finish_reason: str | None = None
    chunks: int = 0
    top_chunk: str | None = None
    answer_preview: str = ""
    latency_ms: float | None = None
    sampled: str | None = None
    open_coding: str | None = None
    failure_mode: str | None = None


class TraceListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    rows: list[TraceRow] = []


class TraceDetail(BaseModel):
    """The whole record, plus whatever a human wrote about it."""

    trace: dict
    sampled: str | None = None
    open_coding: str | None = None
    failure_mode: str | None = None
