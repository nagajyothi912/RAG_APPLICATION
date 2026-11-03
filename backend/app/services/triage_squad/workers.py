"""
workers.py — The two specialists.

Each worker gets a short prompt, only the inputs the orchestrator chose to send,
and only its own tools, offered from the same schemas the single agent sees:

  triage worker   lookup_order_record, escalate_ticket    (no KB, no drafting)
  policy worker   retrieve_kb_context                     (no CRM, no drafting)

Narrow prompts with fewer tools are the one plausible source of a quality win
for the squad, so a worker cannot call a tool outside its set even if the model
asks for one.

Workers return facts as JSON, never customer-facing prose. The escalation note
is taken from the escalate_ticket result itself, not from the model's retelling.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.ticket_reply_app.tools import TOOL_SCHEMAS, dispatch_tool

TRIAGE_TOOLS = ("lookup_order_record", "escalate_ticket")
POLICY_TOOLS = ("retrieve_kb_context",)

TRIAGE_SYSTEM_PROMPT = """\
You are the triage specialist for AirFiber support. Your only job is to decide
whether this ticket needs a formal escalation, based on the customer's account record.

1. Call lookup_order_record with the ticket ID.
2. Call escalate_ticket only if one of these holds: a Priority-tier customer
   asking for a refund or compensation; service paid for but not activated or
   installation visits missed; a relocation or order overdue; repeated contact.
3. Finish with JSON only:
   {"escalated": true|false, "account_facts": "<1-2 sentences of record facts that matter to the reply>"}

Do not write a reply to the customer."""

POLICY_SYSTEM_PROMPT = """\
You are the policy-lookup specialist for AirFiber support. Your only job is to
find the policy that governs the customer's question.

1. Call retrieve_kb_context once with the query you were given.
2. Finish with JSON only:
   {"answerable": true|false, "policy_text": "<the sentences from the passages that govern the question, quoted verbatim>"}

Quote figures exactly as written. Never add a policy that is not in the passages.
Do not write a reply to the customer."""

WORKER_MAX_ITERATIONS = 3


def _schemas(names: Tuple[str, ...]) -> List[Dict[str, Any]]:
    return [s for s in TOOL_SCHEMAS if s["function"]["name"] in names]


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def recover_final_answer(exc: Exception, allowed: Tuple[str, ...]) -> Optional[str]:
    """
    gpt-oss on Groq sometimes emits its final JSON as a call to a made-up tool
    ("json"), and Groq rejects the whole turn with a 400 `tool_use_failed`. The
    answer is intact in `failed_generation`, so take it instead of failing the
    hand-off. Anything else, including a bad call to a real tool, still raises.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    if not isinstance(body, dict) or body.get("code") != "tool_use_failed":
        return None
    generated = _parse_json(body.get("failed_generation", ""))
    if not generated or generated.get("name") in allowed or not isinstance(generated.get("arguments"), dict):
        return None
    return json.dumps(generated["arguments"], ensure_ascii=False)


def run_tool_loop(
    client: Any,
    model: str,
    system: str,
    user: str,
    allowed: Tuple[str, ...],
    dispatch: Callable[[str, Dict[str, Any]], Dict[str, Any]],
    max_iterations: int = WORKER_MAX_ITERATIONS,
) -> Tuple[str, List[Dict[str, Any]]]:
    """A small ReAct loop over `allowed` tools. Returns the final text and the tool results."""
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    schemas = _schemas(allowed)
    results: List[Dict[str, Any]] = []
    for _ in range(max_iterations):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=schemas,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=512,
            )
        except Exception as exc:
            recovered = recover_final_answer(exc, allowed)
            if recovered is None:
                raise
            return recovered, results
        message = response.choices[0].message
        if not message.tool_calls:
            return (message.content or "").strip(), results
        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in message.tool_calls
            ],
        })
        for tc in message.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if name in allowed:
                result = dispatch(name, args)
            else:
                result = {"error": f"Tool '{name}' is not available to this worker."}
            results.append({"name": name, "arguments": args, "result": result})
            messages.append({
                "role": "tool", "tool_call_id": tc.id, "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            })
    return "", results


def run_triage_worker(client: Any, model: str, request: Dict[str, Any]) -> Dict[str, Any]:
    """request: ticket_id, tier, tenure_days, refund_requested, brief."""
    user = (
        f"Ticket ID: {request['ticket_id']}\n"
        f"Customer tier: {request['tier']}\n"
        f"Tenure (days): {request['tenure_days']}\n"
        f"Refund requested: {request['refund_requested']}\n"
        f"Brief from the orchestrator: {request.get('brief', '')}"
    )

    def dispatch(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        # Tickets are scoped to the one the orchestrator sent, whatever the model typed.
        args = {**args, "ticket_id": request["ticket_id"]}
        return dispatch_tool(name=name, args=args, client=client, model=model)

    text, results = run_tool_loop(client, model, TRIAGE_SYSTEM_PROMPT, user, TRIAGE_TOOLS, dispatch)
    parsed = _parse_json(text)
    escalations = [r["result"] for r in results if r["name"] == "escalate_ticket"]
    records = [r["result"].get("record") for r in results
               if r["name"] == "lookup_order_record" and r["result"].get("status") == "found"]
    account_facts = (parsed or {}).get("account_facts") or (
        json.dumps(records[-1], ensure_ascii=False) if records else ""
    )
    return {
        "worker": "triage",
        "escalated": bool(escalations),
        "escalation_note": escalations[-1].get("escalation_note", "") if escalations else "",
        "account_facts": account_facts,
        "parsed_output": parsed is not None,
        "tools_called": [r["name"] for r in results],
    }


def run_policy_worker(client: Any, model: str, request: Dict[str, Any], kb_context: str) -> Dict[str, Any]:
    """request: ticket_id, query, question. `kb_context` is what the mock KB returns for this case."""
    user = (
        f"Query: {request['query']}\n"
        f"Customer question: {request['question']}"
    )

    def dispatch(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return dispatch_tool(name=name, args=args, client=client, model=model, context_override=kb_context)

    text, results = run_tool_loop(client, model, POLICY_SYSTEM_PROMPT, user, POLICY_TOOLS, dispatch)
    parsed = _parse_json(text)
    passages = [r["result"].get("passages", "") for r in results if r["name"] == "retrieve_kb_context"]
    # An unparseable answer falls back to the retrieved passages, never to nothing.
    policy_text = (parsed or {}).get("policy_text") or (passages[-1] if passages else "")
    return {
        "worker": "policy",
        "answerable": bool((parsed or {}).get("answerable", bool(policy_text))),
        "policy_text": policy_text,
        "parsed_output": parsed is not None,
        "tools_called": [r["name"] for r in results],
    }
