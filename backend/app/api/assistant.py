"""
/api/assistant - the chat UI's MCP-backed assistant (help centre + ticket history).

The RAG-only /api/chat is unchanged; the admin Week 3/4 tabs still use it.
"""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.schemas import ChatTurn, FollowUpSuggestion
from app.services.assistant import AssistantBusy, AssistantUnavailable, get_assistant
from app.services.auth import AuthUser, current_user, require_admin

router = APIRouter(tags=["assistant"], prefix="/assistant")


class AssistantRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    # Earlier turns, oldest first; the agent sees the last few as prior messages.
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)


class ToolCall(BaseModel):
    server: str
    tool: str
    arguments: dict[str, Any]
    is_error: bool
    latency_ms: float | None = None


class AssistantSource(BaseModel):
    article_id: str
    source_file: str
    section: str
    product_area: str
    preview: str


class AssistantResponse(BaseModel):
    answer: str
    tool_calls: list[ToolCall]
    sources: list[AssistantSource]
    tickets: list[str]
    stop_reason: str
    model_turns: int
    total_tokens: int
    follow_ups: list[FollowUpSuggestion] = []


@router.post("", response_model=AssistantResponse)
async def ask(payload: AssistantRequest, user: AuthUser = Depends(current_user)) -> AssistantResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    try:
        result = await get_assistant().ask(message, user, payload.history)
    except AssistantUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Assistant unavailable: {exc}") from exc
    except AssistantBusy as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Assistant failed: {exc}") from exc
    return AssistantResponse(**result)


@router.get("/servers", dependencies=[Depends(require_admin)])
def servers() -> dict:
    """What the assistant discovered over MCP: servers, transports and tools (admin only)."""
    try:
        return get_assistant().discovery()
    except AssistantUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Assistant unavailable: {exc}") from exc
