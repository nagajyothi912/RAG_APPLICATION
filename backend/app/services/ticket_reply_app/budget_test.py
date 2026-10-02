"""
budget_test.py — Force one budget to fire and save a structured termination log.

Usage
-----
    cd backend
    python -m app.services.ticket_reply_app.budget_test

What it does
------------
Runs the agent on ticket T010 (a dependent-chain ticket) with
MAX_ITERATIONS=2 so the budget fires after the second loop iteration,
before the agent can finish all three tool calls.

Saves the termination log to: eval/week7/budget_termination.log
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(BACKEND))

from openai import OpenAI

from app.config import settings
from app.services.ticket_reply_app.agent import BudgetTracker, run_agent
from app.services.ticket_reply_app.tickets import TICKET_MAP

EVAL_DIR = BACKEND / "eval" / "week7"
EVAL_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = EVAL_DIR / "budget_termination.log"


def run_budget_test() -> None:
    ticket = TICKET_MAP["T010"]
    client = OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
    model  = settings.groq_model

    print("=" * 70)
    print("BUDGET TERMINATION TEST")
    print(f"  Ticket : {ticket['ticket_id']}")
    print(f"  Budget : max_iterations=2  (normal limit is 8)")
    print(f"  Model  : {model}")
    print("=" * 70)

    # Intentionally low iteration budget to force early termination
    budget = BudgetTracker(
        max_iterations=2,
        max_tokens=6000,
        max_cost_usd=0.10,
        max_wall_clock=60.0,
    )

    result = run_agent(ticket, client, model, budget=budget)

    # ── Build the termination log ────────────────────────────────────────────
    log = {
        "test_name":       "budget_termination_test",
        "run_at":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ticket_id":       ticket["ticket_id"],
        "ticket_question": ticket["question"],
        "ticket_tier":     ticket["tier"],
        "model":           model,
        "budget_tested":   "max_iterations",
        "configured_limit": budget.max_iterations,
        "budget_hit":      result["budget_hit"],
        "iterations_completed": result["iterations"],
        "total_tokens":    result["total_tokens"],
        "total_cost_usd":  result["total_cost_usd"],
        "latency_ms":      result["latency_ms"],
        "tools_called_before_termination": result["tools_called"],
        "partial_reply":   result["reply"][:200] if result["reply"] else "(none)",
        "all_budget_config": result["budget_config"],
        "clean_termination": result["budget_hit"] is not None,
        "verdict": (
            "BUDGET HIT — agent terminated cleanly after reaching max_iterations=2. "
            "No exception was raised. The partial state is recorded above."
            if result["budget_hit"] == "max_iterations"
            else "Budget did NOT fire as expected — check configuration."
        ),
    }

    LOG_PATH.write_text(
        json.dumps(log, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("\n[RESULT]")
    print(f"  budget_hit        : {log['budget_hit']}")
    print(f"  iterations done   : {log['iterations_completed']} / {log['configured_limit']}")
    print(f"  tools before stop : {log['tools_called_before_termination']}")
    print(f"  tokens used       : {log['total_tokens']}")
    print(f"  clean termination : {log['clean_termination']}")
    print(f"\n  Log saved → {LOG_PATH}")
    print(f"\n  Verdict: {log['verdict']}")


if __name__ == "__main__":
    run_budget_test()
