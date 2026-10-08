"""
Week 6 API: the committed LLM-judge runs, read-only.

Serves what backend/scripts/evaluate_week6.py already wrote to
backend/eval/week6/runs/ - nothing is recomputed against the model here. The
only derived numbers are counts over those files: agreement, per-mode
agreement, and agreement with the few-shot tickets held out (the tickets are
read from judge_v2.txt, not hard-coded, so they track the prompt).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["week6"])

WEEK6_DIR = Path(__file__).resolve().parents[2] / "eval" / "week6"
RUNS_DIR = WEEK6_DIR / "runs"

# (label, file glob, description). The newest match wins for a glob.
RUN_FILES = [
    ("v1 · single run", "judge_v1_results.json", "Zero-shot judge, the pre-iteration run."),
    ("v1 · majority of 3", "judge_v1_2*.json", "Zero-shot judge, re-run 3 times, majority vote."),
    ("v2 · majority of 3", "judge_v2_2*.json", "Few-shot judge built from v1's disagreements."),
]


class Week6Run(BaseModel):
    label: str
    description: str
    file: str
    judge: str
    model: str
    run_at: str
    labels_commit: str
    runs: int
    agreement_per_run: List[int]
    agree: int
    total: int
    held_out_agree: int
    held_out_total: int
    by_mode: Dict[str, Dict[str, int]]
    results: List[Dict[str, Any]]


class Week6Response(BaseModel):
    available: bool
    few_shot_tickets: List[str] = []
    prediction: Optional[str] = None
    runs: List[Week6Run] = []


def _few_shot_tickets() -> list[str]:
    prompt = WEEK6_DIR / "judge_v2.txt"
    if not prompt.exists():
        return []
    return sorted(set(re.findall(r"\bT\d{3}\b", prompt.read_text("utf-8"))))


def _load_run(label: str, pattern: str, description: str, few_shot: set[str]) -> Optional[Week6Run]:
    matches = sorted(RUNS_DIR.glob(pattern))
    if not matches:
        return None
    path = matches[-1]
    data = json.loads(path.read_text("utf-8"))
    results = data.get("results", [])

    by_mode: Dict[str, Dict[str, int]] = {}
    for row in results:
        bucket = by_mode.setdefault(row.get("week5_mode", "unknown"), {"agree": 0, "total": 0})
        bucket["total"] += 1
        bucket["agree"] += int(bool(row.get("agree")))

    held_out = [row for row in results if row.get("ticket_id") not in few_shot]
    return Week6Run(
        label=label,
        description=description,
        file=path.name,
        judge=data.get("judge", ""),
        model=data.get("model", ""),
        run_at=data.get("run_at", ""),
        labels_commit=data.get("labels_commit", ""),
        runs=int(data.get("runs", 1)),
        agreement_per_run=data.get("agreement_per_run") or [sum(bool(r.get("agree")) for r in results)],
        agree=sum(bool(r.get("agree")) for r in results),
        total=len(results),
        held_out_agree=sum(bool(r.get("agree")) for r in held_out),
        held_out_total=len(held_out),
        by_mode=by_mode,
        results=results,
    )


@router.get("/week6/results", response_model=Week6Response)
def get_week6_results() -> Week6Response:
    if not RUNS_DIR.exists():
        return Week6Response(available=False)
    try:
        few_shot = _few_shot_tickets()
        runs = [
            run
            for label, pattern, description in RUN_FILES
            if (run := _load_run(label, pattern, description, set(few_shot))) is not None
        ]
        prediction_file = WEEK6_DIR / "prediction.txt"
        prediction = prediction_file.read_text("utf-8").strip() if prediction_file.exists() else None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read Week 6 runs: {exc}") from exc
    return Week6Response(
        available=bool(runs),
        few_shot_tickets=few_shot,
        prediction=prediction,
        runs=runs,
    )
