"""
worker_api.py — The two workers as an HTTP service.

The orchestrator reaches its workers over HTTP, so an injected failure is a
genuine HTTP 500 on the wire rather than a flag the orchestrator can peek at.
Each response carries the worker's own ledger, so every token spent behind
the hand-off still shows up in the orchestrator's log.

The injected 500 fires before the worker spends a token: a failed hand-off
costs nothing but the time the orchestrator waits.
"""

from __future__ import annotations

from typing import Any, Dict, Set

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .metering import CURRENT_HOP, Ledger, MeteredClient, QuotaExhausted
from .workers import run_policy_worker, run_triage_worker

TRIAGE_HOP = "orchestrator -> triage worker"
POLICY_HOP = "orchestrator -> policy worker"


class TriageRequest(BaseModel):
    ticket_id: str
    tier: str
    tenure_days: int
    refund_requested: bool
    brief: str = ""


class PolicyRequest(BaseModel):
    ticket_id: str
    query: str
    question: str


class FailureInjector:
    """Which tickets the policy worker answers with a 500. Mutable, so the race can arm it."""

    def __init__(self) -> None:
        self.policy_fail_on: Set[str] = set()
        self.hits: Dict[str, int] = {}

    def should_fail(self, ticket_id: str) -> bool:
        if ticket_id in self.policy_fail_on:
            self.hits[ticket_id] = self.hits.get(ticket_id, 0) + 1
            return True
        return False


def create_worker_app(
    base_client: Any,
    model: str,
    kb: Dict[str, str],
    injector: FailureInjector | None = None,
) -> FastAPI:
    """`kb` maps ticket id -> the context the mock retrieve_kb_context returns for it."""
    app = FastAPI(title="AirFiber triage squad workers")
    app.state.injector = injector or FailureInjector()

    def _quota_response(exc: Exception) -> JSONResponse:
        # 503, not 500: running out of Groq quota is not the failure under test,
        # and the race must abort rather than score it.
        return JSONResponse(status_code=503, content={"error": str(exc), "quota_exhausted": True, "calls": []})

    def _meter(hop: str) -> MeteredClient:
        CURRENT_HOP.set(hop)
        return MeteredClient(base_client, Ledger())

    @app.post("/workers/triage")
    def triage(request: TriageRequest) -> Dict[str, Any]:
        client = _meter(TRIAGE_HOP)
        try:
            result = run_triage_worker(client, model, request.model_dump())
        except QuotaExhausted as exc:
            return _quota_response(exc)
        return {"result": result, "calls": client.ledger.records}

    @app.post("/workers/policy")
    def policy(request: PolicyRequest):
        if app.state.injector.should_fail(request.ticket_id):
            return JSONResponse(
                status_code=500,
                content={"error": "policy-lookup worker: injected failure", "calls": []},
            )
        client = _meter(POLICY_HOP)
        try:
            result = run_policy_worker(client, model, request.model_dump(), kb.get(request.ticket_id, ""))
        except QuotaExhausted as exc:
            return _quota_response(exc)
        return {"result": result, "calls": client.ledger.records}

    return app
