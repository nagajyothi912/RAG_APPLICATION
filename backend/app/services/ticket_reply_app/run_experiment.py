"""
run_experiment.py — Run both systems on all 10 tickets and persist results.

Usage
-----
    cd backend
    python -m app.services.ticket_reply_app.run_experiment

Output
------
    backend/eval/week7/agent_results.json
    backend/eval/week7/workflow_results.json
    backend/eval/week7/comparison_table.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(BACKEND))

from openai import OpenAI

from app.config import settings
from app.services.ticket_reply_app.agent import BudgetTracker, run_agent
from app.services.ticket_reply_app.fixed_workflow import run_fixed_workflow
from app.services.ticket_reply_app.metrics import build_comparison_table
from app.services.ticket_reply_app.tickets import TICKETS

EVAL_DIR = BACKEND / "eval" / "week7"
EVAL_DIR.mkdir(parents=True, exist_ok=True)


def _client() -> OpenAI:
    return OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)


def run_all() -> None:
    client = _client()
    model  = settings.groq_model

    print("=" * 70)
    print(f"WEEK 7 EXPERIMENT  |  model={model}  |  tickets={len(TICKETS)}")
    print("=" * 70)

    # ── Agent runs ──────────────────────────────────────────────────────────
    agent_results = []
    print("\n[AGENT] Running on all 10 tickets …")
    for ticket in TICKETS:
        budget = BudgetTracker()  # fresh budget per ticket
        result = run_agent(ticket, client, model, budget=budget)
        agent_results.append(result)
        status = "PASS" if _quick_pass(ticket, result["reply"]) else "FAIL"
        bh     = f"  ← budget:{result['budget_hit']}" if result["budget_hit"] else ""
        print(
            f"  [{status}] {ticket['ticket_id']}"
            f"  tools={result['tools_called']}"
            f"  tokens={result['total_tokens']}"
            f"  {result['latency_ms']:.0f}ms"
            f"{bh}"
        )

    # ── Fixed-workflow runs ──────────────────────────────────────────────────
    workflow_results = []
    print("\n[FIXED WORKFLOW] Running on all 10 tickets …")
    for ticket in TICKETS:
        result = run_fixed_workflow(ticket, client, model)
        workflow_results.append(result)
        status = "PASS" if _quick_pass(ticket, result["reply"]) else "FAIL"
        print(
            f"  [{status}] {ticket['ticket_id']}"
            f"  tools={result['tools_called']}"
            f"  tokens={result['total_tokens']}"
            f"  {result['latency_ms']:.0f}ms"
        )

    # ── Build comparison table ───────────────────────────────────────────────
    table = build_comparison_table(agent_results, workflow_results, TICKETS)

    # ── Persist ─────────────────────────────────────────────────────────────
    _write(EVAL_DIR / "agent_results.json", agent_results)
    _write(EVAL_DIR / "workflow_results.json", workflow_results)
    _write(EVAL_DIR / "comparison_table.json", table)

    # ── Print summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("COMPARISON TABLE")
    print("=" * 70)
    _print_table(table)
    print(f"\nResults saved to {EVAL_DIR}")


def _quick_pass(ticket, reply: str) -> bool:
    """Quick pass check without importing the full metrics module at top level."""
    from app.services.ticket_reply_app.metrics import passed
    return passed(ticket, reply)


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _print_table(table: dict) -> None:
    a = table["agent"]
    w = table["fixed_workflow"]
    rows = [
        ("Metric",                 "Agent",                         "Fixed Workflow"),
        ("Pass rate",              f"{a['pass_rate']*100:.0f}%",    f"{w['pass_rate']*100:.0f}%"),
        ("P50 latency (ms)",       f"{a['p50_latency_ms']:.0f}",    f"{w['p50_latency_ms']:.0f}"),
        ("Total tokens (all 10)",  str(a["total_tokens"]),           str(w["total_tokens"])),
        ("Cost / ticket (USD)",    f"${a['cost_per_ticket_usd']:.5f}", f"${w['cost_per_ticket_usd']:.5f}"),
    ]
    col_w = [max(len(r[c]) for r in rows) for c in range(3)]
    sep   = "+-" + "-+-".join("-" * w for w in col_w) + "-+"
    for i, row in enumerate(rows):
        if i == 1:
            print(sep)
        line = "| " + " | ".join(cell.ljust(col_w[j]) for j, cell in enumerate(row)) + " |"
        print(line)
    print(sep)


if __name__ == "__main__":
    run_all()
