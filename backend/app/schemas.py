from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)


class SourceChunk(BaseModel):
    source: str
    chunk_id: int
    score: float
    preview: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]


class SkippedFile(BaseModel):
    filename: str
    reason: str


class UploadResponse(BaseModel):
    uploaded: list[str]
    skipped: list[SkippedFile]
    indexed_chunks: int
    documents: list[str]


class DocumentListResponse(BaseModel):
    documents: list[str]
    indexed_chunks: int


class HealthResponse(BaseModel):
    status: str
    embedder_ready: bool
    llm_configured: bool
    indexed_chunks: int
