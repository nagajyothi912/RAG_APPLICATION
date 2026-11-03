"""
orchestrator.py — Decompose, delegate to both workers in parallel, synthesise.

  1. ticket -> orchestrator (decompose)   one LLM call: a triage brief and a policy query
  2. orchestrator -> triage worker  ┐     run concurrently over HTTP; neither needs
     orchestrator -> policy worker  ┘     the other's output, which is the parallelism
                                           the pattern is supposed to buy
  3. workers -> orchestrator (synthesis)  generate_ticket_reply, the same reply tool
                                           the single agent calls, so the race tests
                                           the pattern rather than a different writer

Context strategy: each worker gets only what its job needs. Triage gets the
ticket's metadata and a brief, never the KB; policy gets a query and the
question, never the account. The decompose step never sees the KB context either.

On a failed hand-off (5xx or no response) the orchestrator retries once, then
carries on with whatever it has and marks the run degraded. What the synthesiser
then writes is the behaviour the failure run records; nothing here forces it.
"""

from __future__ import annotations

import contextvars
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from app.services.ticket_reply_app.tools import generate_ticket_reply

from .metering import CURRENT_HOP, Ledger, MeteredClient, QuotaExhausted
from .worker_api import POLICY_HOP, TRIAGE_HOP

DECOMPOSE_HOP = "ticket -> orchestrator (decompose)"
SYNTHESIS_HOP = "workers -> orchestrator (synthesis)"

HANDOFF_RETRIES = 1

DECOMPOSE_SYSTEM_PROMPT = """\
You are the orchestrator for AirFiber ticket replies. Split the ticket into two
independent jobs for your specialists. Reply with JSON only:
{"triage_brief": "<one sentence for the triage specialist: what the customer wants
  and any escalation signals such as refund, compensation, missed installs, delays,
  or repeated contact>",
 "policy_query": "<a short search query for the policy that answers the question>"}"""


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _decompose(client: MeteredClient, model: str, ticket: Dict[str, Any]) -> Dict[str, Any]:
    CURRENT_HOP.set(DECOMPOSE_HOP)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": DECOMPOSE_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Ticket ID: {ticket['ticket_id']}\n"
                f"Customer tier: {ticket['tier']}\n"
                f"Customer question: {ticket['question']}"
            )},
        ],
        temperature=0.0,
        max_tokens=512,
    )
    parsed = _parse_json(response.choices[0].message.content or "")
    return {
        "parsed": parsed is not None,
        # Unparseable plans fall back to the raw question, never to an empty brief.
        "triage_brief": (parsed or {}).get("triage_brief") or ticket["question"],
        "policy_query": (parsed or {}).get("policy_query") or ticket["question"],
    }


def _hand_off(http: Any, path: str, payload: Dict[str, Any], hop: str, ledger: Ledger) -> Dict[str, Any]:
    """POST to a worker, retrying once on a 5xx. Every attempt lands in the ledger."""
    attempts: List[Dict[str, Any]] = []
    for attempt in range(1 + HANDOFF_RETRIES):
        t0 = time.perf_counter()
        try:
            response = http.post(path, json=payload)
            status = response.status_code
            body = response.json()
        except Exception as exc:  # connection refused, timeout, non-JSON body
            status, body = None, {"error": str(exc)}
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        if status == 503 and body.get("quota_exhausted"):
            raise QuotaExhausted(body.get("error", "worker ran out of Groq quota"))
        ledger.extend(body.get("calls", []))
        attempts.append({"attempt": attempt + 1, "status": status, "elapsed_ms": elapsed_ms})
        if status == 200:
            return {"ok": True, "result": body["result"], "attempts": attempts}
        ledger.add({
            "hop": hop, "kind": "hand-off", "status": f"http_{status}" if status else "no_response",
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
            "latency_ms": elapsed_ms, "rate_limit_wait_ms": 0.0,
            "error": body.get("error"),
        })
    return {"ok": False, "result": None, "attempts": attempts}


def run_orchestrator(
    ticket: Dict[str, Any],
    client: MeteredClient,
    model: str,
    http: Any,
) -> Dict[str, Any]:
    """
    One ticket through the squad. `client` meters the orchestrator's own calls;
    `http` is an httpx-style client pointed at the worker service.
    """
    ledger = client.ledger
    wall_start = time.perf_counter()

    plan = _decompose(client, model, ticket)

    triage_payload = {
        "ticket_id": ticket["ticket_id"],
        "tier": ticket["tier"],
        "tenure_days": ticket.get("tenure_days", 0),
        "refund_requested": ticket.get("refund_requested", False),
        "brief": plan["triage_brief"],
    }
    policy_payload = {
        "ticket_id": ticket["ticket_id"],
        "query": plan["policy_query"],
        "question": ticket["question"],
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        triage_future = pool.submit(
            contextvars.copy_context().run, _hand_off, http, "/workers/triage", triage_payload, TRIAGE_HOP, ledger,
        )
        policy_future = pool.submit(
            contextvars.copy_context().run, _hand_off, http, "/workers/policy", policy_payload, POLICY_HOP, ledger,
        )
        triage = triage_future.result()
        policy = policy_future.result()

    triage_out = triage["result"] or {}
    policy_out = policy["result"] or {}
    degraded = [name for name, h in (("triage", triage), ("policy", policy)) if not h["ok"]]

    context_passages = policy_out.get("policy_text", "") if policy["ok"] else (
        "[Policy lookup unavailable: the policy-lookup worker failed and returned no policy text.]"
    )
    if triage_out.get("account_facts"):
        context_passages += f"\n\nAccount record: {triage_out['account_facts']}"
    escalation_note = triage_out.get("escalation_note", "")

    CURRENT_HOP.set(SYNTHESIS_HOP)
    synthesis = generate_ticket_reply(
        client=client,
        model=model,
        ticket_id=ticket["ticket_id"],
        customer_question=ticket["question"],
        context_passages=context_passages,
        tone="apologetic" if escalation_note else "informational",
        customer_tier=ticket["tier"],
        escalation_note=escalation_note,
    )

    return {
        "system": "orchestrator",
        "ticket_id": ticket["ticket_id"],
        "reply": synthesis.get("reply", ""),
        "plan": plan,
        "triage": triage,
        "policy": policy,
        "degraded": degraded,
        "synthesis_context": context_passages,
        "escalation_note": escalation_note,
        "total_tokens": ledger.total_tokens,
        "total_cost_usd": ledger.total_cost,
        "rate_limit_wait_ms": ledger.rate_limit_wait_ms,
        "latency_ms": round((time.perf_counter() - wall_start) * 1000, 1),
        "calls": ledger.records,
    }
