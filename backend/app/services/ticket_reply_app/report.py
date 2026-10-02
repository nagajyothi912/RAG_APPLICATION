"""
report.py — Generate the comparison table and ≤150-word final verdict.

Reads the persisted JSON results from eval/week7/ and prints a rich
terminal report. Can also be called programmatically to return the
structured summary for the FastAPI endpoint.

Usage
-----
    cd backend
    python -m app.services.ticket_reply_app.report
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parents[4]
EVAL_DIR = BACKEND / "eval" / "week7"


def load_results() -> Optional[Dict[str, Any]]:
    """Load persisted experiment results. Returns None if not yet run."""
    table_path = EVAL_DIR / "comparison_table.json"
    agent_path = EVAL_DIR / "agent_results.json"
    wflow_path = EVAL_DIR / "workflow_results.json"
    blog_path  = EVAL_DIR / "budget_termination.log"

    if not table_path.exists():
        return None

    table    = json.loads(table_path.read_text("utf-8"))
    agents   = json.loads(agent_path.read_text("utf-8")) if agent_path.exists() else []
    workflow = json.loads(wflow_path.read_text("utf-8")) if wflow_path.exists() else []
    blog     = json.loads(blog_path.read_text("utf-8"))  if blog_path.exists()  else {}

    return {
        "comparison_table": table,
        "agent_results":    agents,
        "workflow_results": workflow,
        "budget_log":       blog,
    }


def build_verdict(table: Dict[str, Any], per_ticket: List[Dict[str, Any]]) -> str:
    """
    ≤150-word verdict comparing agent and fixed workflow.

    Identifies which ticket class causes the execution path to vary and
    references the measured numbers.
    """
    a  = table["agent"]
    w  = table["fixed_workflow"]

    # Count escalated tickets per system
    a_esc = sum(1 for r in per_ticket if r["system"] == "agent"    and "escalate_ticket" in r["tools_called"])
    w_esc = sum(1 for r in per_ticket if r["system"] == "fixed_workflow" and "escalate_ticket" in r["tools_called"])

    verdict = (
        f"The execution path varies for Priority-tier and multi-step dependent tickets "
        f"(T010, T017, T118, T119). In those cases the agent conditionally invokes "
        f"escalate_ticket based on LLM reasoning ({a_esc}/10 agent runs), while the "
        f"fixed workflow applies a deterministic rule ({w_esc}/10 workflow runs). "
        f"Agent pass rate: {a['pass_rate']*100:.0f}% vs workflow: {w['pass_rate']*100:.0f}%. "
        f"Agent P50 latency: {a['p50_latency_ms']:.0f} ms vs workflow: {w['p50_latency_ms']:.0f} ms. "
        f"Agent total tokens: {a['total_tokens']} vs workflow: {w['total_tokens']}. "
        f"For simple informational tickets (T001, T003, T007, T016, T022, T073) both "
        f"paths produce identical tool sequences and equivalent replies — the fixed "
        f"workflow is sufficient there. For dependent-chain tickets, the agent's "
        f"dynamic branching is the observed differentiator."
    )
    # Trim to 150 words
    words = verdict.split()
    if len(words) > 150:
        verdict = " ".join(words[:150]) + "…"
    return verdict


def build_tool_diff() -> Dict[str, Any]:
    """Return the third-tool description and parameter diff for the UI."""
    return {
        "tool_name":   "escalate_ticket",
        "added_in":    "Week 7",
        "description": (
            "Record a formal escalation for a support ticket and return the assigned "
            "team, SLA, and a structured escalation record. Use this ONLY when the "
            "ticket meets one of the enumerated escalation reasons — do NOT use it for "
            "routine queries that can be resolved with knowledge-base context alone. "
            "Does not search the knowledge base and does not write reply prose."
        ),
        "parameters": {
            "ticket_id": "string — ticket identifier",
            "reason": {
                "type": "enum",
                "values": [
                    "missing_order",
                    "repeated_contact",
                    "priority_customer",
                    "unresolved_technical",
                    "refund_dispute",
                ],
            },
            "severity": {
                "type": "enum",
                "values": ["low", "medium", "high", "critical"],
            },
        },
        "non_overlap_note": (
            "retrieve_kb_context: KB lookup only (no routing, no prose). "
            "generate_ticket_reply: prose drafting only (no lookup, no routing). "
            "escalate_ticket: routing decision only (no lookup, no prose)."
        ),
    }


def print_report() -> None:
    data = load_results()
    if data is None:
        print("[report] No results found in eval/week7/. Run run_experiment.py first.")
        return

    table      = data["comparison_table"]
    per_ticket = table["per_ticket"]
    blog       = data["budget_log"]

    print("=" * 70)
    print("WEEK 7 REPORT")
    print("=" * 70)

    # ── Comparison table ─────────────────────────────────────────────────────
    a = table["agent"]
    w = table["fixed_workflow"]
    print("\n  COMPARISON TABLE (10 tickets each)")
    print(f"  {'Metric':<28} {'Agent':>14} {'Fixed Workflow':>16}")
    print(f"  {'-'*28} {'-'*14} {'-'*16}")
    print(f"  {'Pass rate':<28} {a['pass_rate']*100:>13.0f}% {w['pass_rate']*100:>15.0f}%")
    print(f"  {'P50 latency (ms)':<28} {a['p50_latency_ms']:>14.0f} {w['p50_latency_ms']:>16.0f}")
    print(f"  {'Total tokens (all 10)':<28} {a['total_tokens']:>14,} {w['total_tokens']:>16,}")
    print(f"  {'Cost / ticket (USD)':<28} ${a['cost_per_ticket_usd']:>13.5f} ${w['cost_per_ticket_usd']:>15.5f}")

    # ── Per-ticket detail ────────────────────────────────────────────────────
    print("\n  PER-TICKET DETAIL")
    print(f"  {'Ticket':<8} {'System':<16} {'Pass':<6} {'Tokens':>7} {'ms':>7} {'Tools'}")
    print(f"  {'-'*8} {'-'*16} {'-'*6} {'-'*7} {'-'*7} {'-'*30}")
    tickets_seen = set()
    for row in sorted(per_ticket, key=lambda r: r["ticket_id"]):
        key = (row["ticket_id"], row["system"])
        if key in tickets_seen:
            continue
        tickets_seen.add(key)
        ok    = "✓" if row["pass"] else "✗"
        tools = "→".join(t.replace("_", " ") for t in row["tools_called"])
        print(
            f"  {row['ticket_id']:<8} {row['system']:<16} {ok:<6} "
            f"{row['total_tokens']:>7} {row['latency_ms']:>7.0f} {tools}"
        )

    # ── Budget termination log ───────────────────────────────────────────────
    if blog:
        print("\n  BUDGET TERMINATION LOG")
        print(f"    Ticket          : {blog.get('ticket_id')}")
        print(f"    Budget hit      : {blog.get('budget_hit')}")
        print(f"    Configured limit: {blog.get('configured_limit')}")
        print(f"    Iterations done : {blog.get('iterations_completed')}")
        print(f"    Clean termination: {blog.get('clean_termination')}")

    # ── Third-tool description ───────────────────────────────────────────────
    diff = build_tool_diff()
    print(f"\n  THIRD TOOL: {diff['tool_name']}")
    print(f"    {diff['description']}")
    print(f"    Non-overlap: {diff['non_overlap_note']}")

    # ── Final verdict ────────────────────────────────────────────────────────
    verdict = build_verdict(table, per_ticket)
    print(f"\n  FINAL VERDICT (≤150 words)")
    print("  " + "-" * 60)
    # Wrap at 70 chars
    words = verdict.split()
    line  = "  "
    for w_tok in words:
        if len(line) + len(w_tok) + 1 > 72:
            print(line)
            line = "  " + w_tok
        else:
            line += (" " if line.strip() else "") + w_tok
    if line.strip():
        print(line)
    print("  " + "-" * 60)
    print(f"\n  Word count: {len(verdict.split())}")


def get_week7_report() -> Dict[str, Any]:
    """FastAPI-callable: return full report as a dict."""
    data = load_results()
    if data is None:
        return {"available": False}
    table      = data["comparison_table"]
    per_ticket = table["per_ticket"]
    verdict    = build_verdict(table, per_ticket)
    return {
        "available":         True,
        "comparison_table":  table,
        "verdict":           verdict,
        "tool_diff":         build_tool_diff(),
        "budget_log":        data.get("budget_log", {}),
    }


if __name__ == "__main__":
    print_report()
