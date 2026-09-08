import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.config import settings
from app.services import langfuse_sink
from app.services.rag_service import get_rag_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Loading embedding model and indexing documents in %s", settings.resolved_docs_dir)
    service = get_rag_service()
    logger.info(
        "RAG ready: %s chunks, LLM configured=%s",
        len(service.store.chunks),
        service.llm_configured,
    )
    if langfuse_sink.enabled():
        logger.info("Langfuse tracing on -> %s", settings.langfuse_base_url)
    yield
    # The SDK batches spans and flushes on an interval, so a server stopped
    # shortly after a request would otherwise drop that request's trace.
    langfuse_sink.flush()


app = FastAPI(
    title="Ask My Documents",
    description="Retrieval-Augmented Generation API built around the Week 3 notebook pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
