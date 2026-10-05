"""
Week 8 API endpoint: Serves trajectory evaluation results, failure mode mitigation,
regression checks, and prompt injection attack/defense benchmarks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["week8"])

EVAL_DIR = Path(__file__).resolve().parents[3] / "eval" / "week8"


class Week8Response(BaseModel):
    available: bool
    summary: Optional[Dict[str, Any]] = None
    baseline_eval: Optional[Dict[str, Any]] = None
    mitigated_eval: Optional[Dict[str, Any]] = None
    named_gap_case: Optional[Dict[str, Any]] = None
    regression_table: Optional[List[Dict[str, Any]]] = None
    bonus_challenge: Optional[Dict[str, Any]] = None


@router.get("/week8/results", response_model=Week8Response)
def get_week8_results() -> Week8Response:
    """
    Return stored Week 8 trajectory eval, outcome-vs-trajectory gap,
    mitigation before/after, regression table, and bonus challenge.
    """
    results_file = EVAL_DIR / "trajectory_eval_results.json"
    if not results_file.exists():
        return Week8Response(available=False)

    try:
        with open(results_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Week8Response(
            available=True,
            summary=data.get("summary"),
            baseline_eval=data.get("baseline_eval"),
            mitigated_eval=data.get("mitigated_eval"),
            named_gap_case=data.get("named_gap_case"),
            regression_table=data.get("regression_table"),
            bonus_challenge=data.get("bonus_challenge"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/week8/run")
def trigger_week8_experiment(background_tasks: BackgroundTasks) -> Dict[str, str]:
    """
    Run the full 10-ticket Week 8 trajectory experiment in background.
    """
    try:
        from app.services.ticket_reply_app.trajectory_eval import run_full_week8_experiment

        background_tasks.add_task(run_full_week8_experiment, output_dir=EVAL_DIR)
        return {
            "status": "started",
            "message": "Week 8 trajectory evaluation running in background. Refresh /api/week8/results once finished.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/week8/attack-defense")
def run_attack_defense_demo() -> Dict[str, Any]:
    """
    Run the live Bonus Challenge: Indirect prompt injection attack against
    vulnerable baseline agent and defended agent (with sanitization and output guardrail).
    """
    try:
        from openai import OpenAI
        from app.config import settings
        from app.services.ticket_reply_app.trajectory_eval import run_bonus_injection_eval

        client = OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
        return run_bonus_injection_eval(client, settings.groq_model)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
