"""
metrics.py — Latency, token, cost, and pass/fail helpers.

All metric helpers are pure functions so the experiment runner and the
report module can import them independently without side effects.
"""

from __future__ import annotations

import re
import statistics
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Cost constants (must match agent.py)
# ---------------------------------------------------------------------------
INPUT_COST_PER_TOKEN:  float = 0.09 / 1_000_000
OUTPUT_COST_PER_TOKEN: float = 0.09 / 1_000_000


# ---------------------------------------------------------------------------
# Deterministic assertion functions
# (mirrors evaluate_week6.py so grading is identical)
# ---------------------------------------------------------------------------

def assert_ticket_id_echoed(ticket: Dict[str, Any], reply: str) -> bool:
    tid = ticket.get("ticket_id", "")
    if not tid:
        return True
    return bool(re.search(rf"\b{re.escape(tid)}\b", reply, re.IGNORECASE))


def assert_refund_amount_numeric(ticket: Dict[str, Any], reply: str) -> bool:
    if "refund" in reply.lower() and (
        "eligible for" in reply.lower()
        or "entitled to" in reply.lower()
        or "processed" in reply.lower()
        or "refund of" in reply.lower()
    ):
        return bool(
            re.search(r"₹\s*\d+", reply)
            or re.search(r"\b\d+\s*(rupees|rs|inr)\b", reply, re.IGNORECASE)
        )
    return True


def assert_priority_escalation(ticket: Dict[str, Any], reply: str) -> bool:
    if ticket.get("tier") == "Priority":
        markers = [
            "priority", "escalat", "supervisor",
            "ops lead", "senior", "lead assigned",
        ]
        return any(m in reply.lower() for m in markers)
    return True


def assert_no_refund_outside_30_days(ticket: Dict[str, Any], reply: str) -> bool:
    tenure  = ticket.get("tenure_days", 0)
    refund  = ticket.get("refund_requested", False)
    if tenure > 30 and refund:
        lower = reply.lower()
        if "100% refund" in lower or "full refund of" in lower:
            return False
    return True


ASSERTIONS = {
    "ticket_id_echoed":          assert_ticket_id_echoed,
    "refund_amount_numeric":     assert_refund_amount_numeric,
    "priority_escalation":       assert_priority_escalation,
    "no_refund_outside_30_days": assert_no_refund_outside_30_days,
}


def run_assertions(ticket: Dict[str, Any], reply: str) -> Dict[str, bool]:
    return {name: fn(ticket, reply) for name, fn in ASSERTIONS.items()}


def passed(ticket: Dict[str, Any], reply: str) -> bool:
    """
    A ticket run passes when all applicable assertions (those listed in the
    ticket's 'assertions' dict) return True.
    """
    applicable = ticket.get("assertions", {})
    for name in applicable:
        fn = ASSERTIONS.get(name)
        if fn and not fn(ticket, reply):
            return False
    return True


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def p50(values: List[float]) -> float:
    """Median (P50) of a list of floats.  Returns 0.0 for empty input."""
    if not values:
        return 0.0
    return statistics.median(values)


def pass_rate(results: List[Dict[str, Any]], tickets: List[Dict[str, Any]]) -> float:
    """Fraction of tickets that pass all applicable assertions (0.0 – 1.0)."""
    if not results:
        return 0.0
    ticket_map = {t["ticket_id"]: t for t in tickets}
    n_pass = sum(
        1
        for r in results
        if passed(ticket_map[r["ticket_id"]], r.get("reply", ""))
    )
    return n_pass / len(results)


def total_tokens_all(results: List[Dict[str, Any]]) -> int:
    return sum(r.get("total_tokens", 0) for r in results)


def total_cost_all(results: List[Dict[str, Any]]) -> float:
    return sum(r.get("total_cost_usd", 0.0) for r in results)


def cost_per_ticket(results: List[Dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return total_cost_all(results) / len(results)


def per_ticket_detail(
    result: Dict[str, Any],
    ticket: Dict[str, Any],
) -> Dict[str, Any]:
    """One-row summary for a single ticket run."""
    reply    = result.get("reply", "")
    asserts  = run_assertions(ticket, reply)
    ok       = passed(ticket, reply)
    return {
        "ticket_id":      result["ticket_id"],
        "system":         result["system"],
        "pass":           ok,
        "latency_ms":     result.get("latency_ms", 0.0),
        "total_tokens":   result.get("total_tokens", 0),
        "total_cost_usd": result.get("total_cost_usd", 0.0),
        "tools_called":   result.get("tools_called", []),
        "iterations":     result.get("iterations", 0),
        "budget_hit":     result.get("budget_hit"),
        "assertions":     asserts,
        "reply_preview":  reply[:160],
    }


def build_comparison_table(
    agent_results:    List[Dict[str, Any]],
    workflow_results: List[Dict[str, Any]],
    tickets:          List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build the 4-metric comparison table.

    Returns
    -------
    {
      "agent":    {pass_rate, p50_latency_ms, total_tokens, cost_per_ticket},
      "workflow": {pass_rate, p50_latency_ms, total_tokens, cost_per_ticket},
      "per_ticket": [ ... per-ticket detail rows ... ],
    }
    """
    a_latencies = [r["latency_ms"] for r in agent_results]
    w_latencies = [r["latency_ms"] for r in workflow_results]

    combined_per_ticket = []
    ticket_map = {t["ticket_id"]: t for t in tickets}
    for ar in agent_results:
        combined_per_ticket.append(per_ticket_detail(ar, ticket_map[ar["ticket_id"]]))
    for wr in workflow_results:
        combined_per_ticket.append(per_ticket_detail(wr, ticket_map[wr["ticket_id"]]))

    return {
        "agent": {
            "pass_rate":       round(pass_rate(agent_results, tickets), 3),
            "p50_latency_ms":  round(p50(a_latencies), 1),
            "total_tokens":    total_tokens_all(agent_results),
            "cost_per_ticket_usd": round(cost_per_ticket(agent_results), 6),
        },
        "fixed_workflow": {
            "pass_rate":       round(pass_rate(workflow_results, tickets), 3),
            "p50_latency_ms":  round(p50(w_latencies), 1),
            "total_tokens":    total_tokens_all(workflow_results),
            "cost_per_ticket_usd": round(cost_per_ticket(workflow_results), 6),
        },
        "per_ticket": combined_per_ticket,
    }
