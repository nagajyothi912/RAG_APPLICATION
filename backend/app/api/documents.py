from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.schemas import (
    DocumentListResponse,
    GoldenSetResponse,
    HealthResponse,
    UploadResponse,
)
from app.services.rag_service import SCORE_THRESHOLD, SUPPORTED_EXTENSIONS, get_rag_service
from app.services.retrieval import availability

router = APIRouter(tags=["documents"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    service = get_rag_service()
    return HealthResponse(
        status="ok",
        embedder_ready=service.store.embedder is not None,
        llm_configured=service.llm_configured,
        indexed_chunks=len(service.store.chunks),
        chunk_strategy=service.strategy,
        chunk_size=service.chunk_size,
        chunk_overlap=service.overlap,
        top_k=service.top_k,
        score_threshold=SCORE_THRESHOLD,
        **availability(),
    )


@router.get("/golden-questions", response_model=GoldenSetResponse)
def golden_questions() -> GoldenSetResponse:
    """The curated question set the chat UI offers as one-click prompts."""
    service = get_rag_service()
    return GoldenSetResponse(questions=service.golden_questions())


@router.get("/documents", response_model=DocumentListResponse)
def list_documents() -> DocumentListResponse:
    service = get_rag_service()
    return DocumentListResponse(
        documents=service.list_documents(),
        indexed_chunks=len(service.store.chunks),
        metadata=service.document_metadata(),
        product_areas=service.product_areas(),
    )


@router.post("/documents/upload", response_model=UploadResponse)
async def upload_documents(files: list[UploadFile] = File(...)) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    payload: list[tuple[str, bytes]] = []
    for upload in files:
        content = await upload.read()
        payload.append((upload.filename or "", content))

    service = get_rag_service()
    try:
        result = service.ingest_uploads(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to index documents: {exc}") from exc

    if not result["uploaded"] and result["skipped"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "None of the uploaded files could be processed.",
                "skipped": result["skipped"],
                "supported_types": sorted(SUPPORTED_EXTENSIONS),
            },
        )

    return UploadResponse(**result)


@router.delete("/documents", response_model=DocumentListResponse)
def delete_document(name: str = Query(..., min_length=1)) -> DocumentListResponse:
    service = get_rag_service()
    try:
        result = service.delete_document(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {exc}") from exc

    return DocumentListResponse(
        **result,
        metadata=service.document_metadata(),
        product_areas=service.product_areas(),
    )
