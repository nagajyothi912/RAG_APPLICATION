"""
fixed_workflow.py — Hard-coded ticket-reply workflow.

Identical inputs, tools, LLM model and output contract as the agent,
but with NO agent loop and NO LLM decision-making about which tool to call.
Every step is explicitly hard-coded in the function body.

Decision rule
-------------
Step 1 (retrieve) → always.
Step 2 (escalate) → if (tier == Priority AND refund_requested) OR
                       (account status is 'unactivated' or 'pending')
                       OR repeated_contact detected.
Step 3 (generate) → always, using context from step 1 and note from step 2.

This fixed branching means the workflow ALWAYS escalates Priority+refund
tickets (including T118, which a human would argue does not need escalation
since only a credit applies), illustrating where the agent path differs.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from .tools import (
    ACCOUNT_DB,
    dispatch_tool,
    escalate_ticket,
    generate_ticket_reply,
    retrieve_kb_context,
)

# Replicate budget cost constants for token accounting
INPUT_COST_PER_TOKEN:  float = 0.09 / 1_000_000
OUTPUT_COST_PER_TOKEN: float = 0.09 / 1_000_000


def _should_escalate(ticket: Dict[str, Any]) -> Optional[str]:
    """
    Deterministic escalation rule — no LLM involved.

    Returns the escalation reason string, or None if no escalation is needed.
    """
    tid    = ticket["ticket_id"]
    tier   = ticket.get("tier", "Standard")
    refund = ticket.get("refund_requested", False)
    tenure = ticket.get("tenure_days", 0)

    account = ACCOUNT_DB.get(tid, {})
    status  = account.get("status", "active")
    missed  = account.get("missed_install_appointments", 0)
    pending_days = account.get("relocation_days_pending", 0)

    # Order/activation not completed and payment exists
    if status == "unactivated" or missed >= 2:
        return "missing_order"

    # Long-pending relocation
    if pending_days >= 14:
        return "missing_order"

    # Priority tier with unresolved refund request
    if tier == "Priority" and refund:
        return "priority_customer"

    # Customer contacted > once (approximated by repeated_contact flag)
    question_lower = ticket.get("question", "").lower()
    repeated_keywords = ["third time", "again", "nobody called", "every week"]
    if any(kw in question_lower for kw in repeated_keywords):
        return "repeated_contact"

    return None


def _severity(reason: str, ticket: Dict[str, Any]) -> str:
    if reason == "missing_order":
        return "high"
    if reason == "priority_customer":
        return "high"
    if reason == "repeated_contact":
        return "medium"
    return "medium"


def run_fixed_workflow(
    ticket: Dict[str, Any],
    client: OpenAI,
    model: str,
) -> Dict[str, Any]:
    """
    Execute the fixed workflow for one ticket.

    Returns the same result shape as the agent (reply, tools_called,
    tool_results, iterations, total_tokens, total_cost_usd, latency_ms,
    budget_hit, budget_config).
    """
    wall_start    = time.perf_counter()
    tools_called: List[str]          = []
    tool_results: List[Dict[str, Any]] = []
    total_tokens  = 0
    total_cost    = 0.0
    escalation_note = ""

    # ── Step 1: Retrieve KB context (always) ─────────────────────────────────
    retrieve_args = {
        "query":        ticket["question"],
        "product_area": "any",
        "top_k":        3,
    }
    r1 = dispatch_tool(
        name="retrieve_kb_context",
        args=retrieve_args,
        client=client,
        model=model,
        context_override=ticket.get("context"),
    )
    tools_called.append("retrieve_kb_context")
    tool_results.append(r1)
    context_passages = r1.get("passages", "")

    # ── Step 2: Escalate (conditionally, rule-based) ──────────────────────────
    reason = _should_escalate(ticket)
    if reason:
        severity = _severity(reason, ticket)
        r2 = dispatch_tool(
            name="escalate_ticket",
            args={
                "ticket_id": ticket["ticket_id"],
                "reason":    reason,
                "severity":  severity,
            },
            client=client,
            model=model,
        )
        tools_called.append("escalate_ticket")
        tool_results.append(r2)
        escalation_note = r2.get("escalation_note", "")

    # ── Step 3: Generate reply (always) ─────────────────────────────────────
    tone = "apologetic" if reason else "informational"
    r3 = dispatch_tool(
        name="generate_ticket_reply",
        args={
            "ticket_id":         ticket["ticket_id"],
            "customer_question": ticket["question"],
            "context_passages":  context_passages,
            "escalation_note":   escalation_note,
            "tone":              tone,
            "customer_tier":     ticket.get("tier", "Standard"),
        },
        client=client,
        model=model,
    )
    tools_called.append("generate_ticket_reply")
    tool_results.append(r3)

    # Accumulate token cost from the one LLM call (generate_ticket_reply)
    for r in tool_results:
        p_tok = r.get("prompt_tokens", 0) or 0
        c_tok = r.get("completion_tokens", 0) or 0
        total_tokens += p_tok + c_tok
        total_cost   += p_tok * INPUT_COST_PER_TOKEN + c_tok * OUTPUT_COST_PER_TOKEN

    latency_ms = (time.perf_counter() - wall_start) * 1000
    return {
        "system":         "fixed_workflow",
        "ticket_id":      ticket["ticket_id"],
        "reply":          r3.get("reply", ""),
        "tools_called":   tools_called,
        "tool_results":   tool_results,
        "iterations":     1,   # fixed: always exactly 3 steps, 1 pass
        "total_tokens":   total_tokens,
        "total_cost_usd": total_cost,
        "latency_ms":     round(latency_ms, 2),
        "budget_hit":     None,
        "budget_config":  {},
        "messages":       [],  # no conversation — hardcoded, no loop
    }
