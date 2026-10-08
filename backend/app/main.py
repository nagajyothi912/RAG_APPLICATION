import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analysis import router as analysis_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.week6 import router as week6_router
from app.api.week7 import router as week7_router
from app.api.week8 import router as week8_router
from app.config import settings
from app.services import langfuse_sink
from app.services.auth import current_user, require_admin, warn_on_default_credentials
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
    warn_on_default_credentials()
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

# Role-based access. The chatbot role can chat and read the library; everything
# that changes the index or shows a week's evaluation is admin-only. The
# documents router guards its own routes, since /health stays public and
# upload/delete need admin while listing does not.
signed_in = [Depends(current_user)]
admin_only = [Depends(require_admin)]

app.include_router(auth_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(chat_router, prefix="/api", dependencies=signed_in)
app.include_router(analysis_router, prefix="/api", dependencies=admin_only)
app.include_router(week6_router, prefix="/api", dependencies=admin_only)
app.include_router(week7_router, prefix="/api", dependencies=admin_only)
app.include_router(week8_router, prefix="/api", dependencies=admin_only)
