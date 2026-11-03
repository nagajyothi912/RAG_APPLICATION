"""
Week 10 API: the saved single-agent vs triage-squad race, read-only.

There is deliberately no route that runs the race. A run costs ~115k Groq
tokens, and a button makes it easy to re-run the squad until it wins, which
is exactly the sunk-cost move the brief warns against. Run it from the CLI:
python -m app.services.triage_squad.race
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["week10"])


@router.get("/week10/report")
def get_week10_report() -> Dict[str, Any]:
    """The four numbers for both arms, hand-offs, per-ticket runs, the failure case and the verdict."""
    try:
        from app.services.triage_squad.report import build_week10_report

        return build_week10_report()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
