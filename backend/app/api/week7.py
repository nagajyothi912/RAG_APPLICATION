"""
Week 7 API endpoint: serves experiment results and can trigger runs.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional

router = APIRouter(tags=["week7"])


class Week7ReportResponse(BaseModel):
    available: bool
    comparison_table: Optional[Dict[str, Any]] = None
    verdict: Optional[str] = None
    tool_diff: Optional[Dict[str, Any]] = None
    budget_log: Optional[Dict[str, Any]] = None


@router.get("/week7/report", response_model=Week7ReportResponse)
def get_report() -> Week7ReportResponse:
    """
    Return the Week 7 comparison table, verdict, tool diff, and budget log.
    Returns {available: false} when the experiment has not been run yet.
    """
    try:
        from app.services.ticket_reply_app.report import get_week7_report
        data = get_week7_report()
        return Week7ReportResponse(**data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/week7/run")
def trigger_experiment(background_tasks: BackgroundTasks) -> Dict[str, str]:
    """
    Kick off the 10-ticket experiment in the background.
    Results appear at /api/week7/report once complete.
    """
    try:
        from app.services.ticket_reply_app.run_experiment import run_all
        background_tasks.add_task(run_all)
        return {"status": "started", "message": "Experiment running in background — poll /api/week7/report"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/week7/budget-test")
def trigger_budget_test(background_tasks: BackgroundTasks) -> Dict[str, str]:
    """
    Run the budget-termination test in the background.
    Log appears at eval/week7/budget_termination.log.
    """
    try:
        from app.services.ticket_reply_app.budget_test import run_budget_test
        background_tasks.add_task(run_budget_test)
        return {"status": "started", "message": "Budget test running — check eval/week7/budget_termination.log"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
