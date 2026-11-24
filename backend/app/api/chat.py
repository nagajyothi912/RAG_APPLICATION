from fastapi import APIRouter, Depends, Header, HTTPException

from app.services.auth import current_user
from app.schemas import ChatRequest, ChatResponse
from app.services.rag_service import NoDocumentsError, RagGenerationError, get_rag_service

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    user=Depends(current_user),
    x_session_id: str | None = Header(default=None),
) -> ChatResponse:
    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    service = get_rag_service()

    filters: dict = {}
    if payload.product_area:
        filters["product_area"] = payload.product_area
    if payload.source_file:
        # Resolve before filtering: an unmatched name must be a 404, not a
        # filter that quietly matches nothing and returns a bare refusal.
        resolved = service.resolve_document(payload.source_file)
        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail=f"No indexed document matches '{payload.source_file}'.",
            )
        filters["source"] = resolved

    try:
        result = service.ask(
            question,
            top_k=payload.top_k,
            filters=filters or None,
            mode=payload.mode,
            history=payload.history,
            # Who asked: the one fact a "wrong answer yesterday" complaint can
            # usually be narrowed by once the time window is known.
            trace_extra={"user": {"user": user.username, "role": user.role, "session_id": x_session_id}},
        )
    except NoDocumentsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RagGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"RAG query failed: {exc}") from exc

    return ChatResponse(**result)
