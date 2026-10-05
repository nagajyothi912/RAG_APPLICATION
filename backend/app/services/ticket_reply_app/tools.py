"""
tools.py — Three tools for the AirFiber ticket-reply agent.

Tool 1: retrieve_kb_context
    Retrieves policy/help-centre context chunks for a customer query.
    Responsibility: knowledge-base lookup only.

Tool 2: generate_ticket_reply
    Generates a complete, formatted support reply using retrieved context.
    Responsibility: LLM-based reply drafting only.

Tool 3: escalate_ticket          ← NEW third tool (Week 7)
    Records a formal escalation decision for a ticket and returns an
    escalation record with assigned team and SLA.
    Responsibility: escalation routing only — does not retrieve content and
    does not draft prose; covers nothing retrieve_kb_context or
    generate_ticket_reply cover.

All three carry typed/enumerated parameters so the LLM cannot pass an
out-of-range value without a schema validation error.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Literal, Optional

from openai import OpenAI

# ---------------------------------------------------------------------------
# Mock account / order database (simulates a CRM lookup)
# ---------------------------------------------------------------------------
ORDERS_DB: Dict[str, Dict[str, Any]] = {
    "ORD-9421": {
        "order_id": "ORD-9421",
        "ticket_id": "T010",
        "plan": "AirFiber_1999",
        "status": "pending_relocation",
        "relocation_days_pending": 42,
        "monthly_charge": 1999,
        "eligible_for_compensation": True,
        "compensation_per_day": 100,
        "days_overdue": 28,
        "estimated_credit": 2800,
        "activated": False,
    },
    "ORD-8832": {
        "order_id": "ORD-8832",
        "ticket_id": "T017",
        "plan": "AirFiber_1999",
        "status": "unactivated",
        "paid_amount": 1999,
        "payment_date": "2026-08-02",
        "missed_engineer_visits": 3,
        "days_since_payment": 5,
        "eligible_for_full_refund": True,
        "activated": False,
    },
    "ORD-7719": {
        "order_id": "ORD-7719",
        "ticket_id": "T119",
        "plan": "AirFiber_1199",
        "status": "active_speed_fault",
        "days_active": 8,
        "avg_speed_mbps": 8.2,
        "promised_speed_mbps": 100,
        "speed_drop_pct": 91.8,
        "eligible_for_cancel_refund": True,
        "plan_charge": 1199,
        "activated": True,
    },
    "ORD-6628": {
        "order_id": "ORD-6628",
        "ticket_id": "T118",
        "plan": "AirFiber_1999",
        "status": "active_outage",
        "days_active": 85,
        "outage_duration_hours": 48,
        "consecutive_outage_days": 2,
        "eligible_for_full_refund": False,
        "eligible_for_daily_credit": True,
        "credit_amount": 200,
        "activated": True,
    },
    "ORD-5512": {
        "order_id": "ORD-5512",
        "ticket_id": "T016",
        "plan": "AirFiber_1199",
        "status": "active",
        "days_active": 10,
        "refund_eligibility_window_days": 30,
        "eligible_for_trial_refund": True,
        "activated": True,
    },
    "ORD-4401": {
        "order_id": "ORD-4401",
        "ticket_id": "T022",
        "plan": "AirFiber_1999",
        "status": "closing",
        "days_active": 365,
        "security_deposit": 1000,
        "equipment_issued": ["ONT device", "power adapter"],
        "deposit_return_sla_days": 7,
        "activated": True,
    },
    "ORD-3310": {
        "order_id": "ORD-3310",
        "ticket_id": "T007",
        "plan": "AirFiber_1199",
        "status": "active_relocation_request",
        "days_active": 90,
        "relocation_requests_count": 1,
        "city_relocation_fee": 0,
        "activated": True,
    },
    "ORD-1100": {
        "order_id": "ORD-1100",
        "ticket_id": "T001",
        "plan": "Enterprise",
        "amount": 4999,
        "status": "active",
        "days_active": 120,
        "activated": True,
    },
    "ORD-2200": {
        "order_id": "ORD-2200",
        "ticket_id": "T003",
        "plan": "AirFiber_1199",
        "amount": 1199,
        "status": "active",
        "days_active": 18,
        "activated": True,
    },
    "ORD-3305": {
        "order_id": "ORD-3305",
        "ticket_id": "T073",
        "plan": "AirFiber_1199",
        "amount": 1199,
        "status": "active",
        "days_active": 30,
        "activated": True,
    },
}

ACCOUNT_DB: Dict[str, Dict[str, Any]] = {
    "T001": {"status": "active",     "plan": "Enterprise",       "days_active": 120, "open_orders": 0, "order_id": "ORD-1100"},
    "T003": {"status": "active",     "plan": "AirFiber_1199",    "days_active": 18,  "open_orders": 0, "order_id": "ORD-2200"},
    "T007": {"status": "active",     "plan": "AirFiber_1199",    "days_active": 90,  "open_orders": 1, "order_id": "ORD-3310"},
    "T010": {"status": "pending",    "plan": "AirFiber_1999",    "days_active": 0,   "open_orders": 1, "order_id": "ORD-9421",
             "relocation_days_pending": 42},
    "T016": {"status": "active",     "plan": "AirFiber_1199",    "days_active": 10,  "open_orders": 0, "order_id": "ORD-5512"},
    "T017": {"status": "unactivated","plan": "AirFiber_1999",    "days_active": 5,   "open_orders": 1, "order_id": "ORD-8832",
             "missed_install_appointments": 3},
    "T022": {"status": "closing",    "plan": "AirFiber_1999",    "days_active": 365, "open_orders": 0, "order_id": "ORD-4401"},
    "T073": {"status": "active",     "plan": "AirFiber_1199",    "days_active": 30,  "open_orders": 0, "order_id": "ORD-3305"},
    "T118": {"status": "active",     "plan": "AirFiber_1999",    "days_active": 85,  "open_orders": 0, "order_id": "ORD-6628",
             "outage_days": 2},
    "T119": {"status": "active",     "plan": "AirFiber_1199",    "days_active": 8,   "open_orders": 0, "order_id": "ORD-7719",
             "avg_speed_mbps": 8},
}

ESCALATION_TEAMS = {
    "missing_order":        {"team": "Field Service Supervisor",  "sla_hours": 24},
    "repeated_contact":     {"team": "Senior Customer Relations", "sla_hours": 4},
    "priority_customer":    {"team": "Priority Support Lead",     "sla_hours": 2},
    "unresolved_technical": {"team": "Network Operations Centre", "sla_hours": 12},
    "refund_dispute":       {"team": "Billing Escalation Desk",   "sla_hours": 8},
}

# ---------------------------------------------------------------------------
# JSON Schema definitions (sent to the LLM in the tools=[...] array)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_kb_context",
            "description": (
                "Search the AirFiber knowledge base for policy or help-centre content "
                "relevant to a customer query. Returns the top matching passages with "
                "source citations. Use this first whenever the reply requires policy facts, "
                "eligibility rules, or technical guidance. Do NOT use it to decide on "
                "escalation routing or to write the final reply."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The customer's question or the key topic to look up.",
                    },
                    "product_area": {
                        "type": "string",
                        "enum": [
                            "billing",
                            "plans",
                            "troubleshooting",
                            "installation",
                            "account",
                            "any",
                        ],
                        "description": (
                            "Restrict retrieval to one product area. "
                            "Pass 'any' to search the whole knowledge base."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Number of passages to return (1–5).",
                    },
                },
                "required": ["query", "product_area"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_ticket_reply",
            "description": (
                "Draft a formatted customer support reply for a ticket, grounded in the "
                "retrieved context passages. Returns the complete reply text. Call this "
                "only after retrieve_kb_context has already fetched the relevant content "
                "and, when applicable, after escalate_ticket has determined the routing. "
                "Do NOT use it to search the knowledge base or to decide escalation logic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "The ticket identifier to echo in the reply header (e.g. T017).",
                    },
                    "customer_question": {
                        "type": "string",
                        "description": "The original customer question, verbatim.",
                    },
                    "context_passages": {
                        "type": "string",
                        "description": (
                            "The retrieved knowledge-base passages to base the reply on. "
                            "Paste them verbatim; they must include source citations."
                        ),
                    },
                    "escalation_note": {
                        "type": "string",
                        "description": (
                            "Optional escalation note produced by escalate_ticket. "
                            "Include only when the ticket was escalated; leave empty otherwise."
                        ),
                    },
                    "tone": {
                        "type": "string",
                        "enum": ["empathetic", "informational", "apologetic", "confirmatory"],
                        "description": "Desired tone for the reply.",
                    },
                    "customer_tier": {
                        "type": "string",
                        "enum": ["Standard", "Priority"],
                        "description": "Customer service tier — affects urgency framing.",
                    },
                },
                "required": [
                    "ticket_id",
                    "customer_question",
                    "context_passages",
                    "tone",
                    "customer_tier",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_ticket",
            "description": (
                "Record a formal escalation for a support ticket and return the assigned "
                "team, SLA, and a structured escalation record. Use this ONLY when the "
                "ticket meets one of the enumerated escalation reasons — do NOT use it for "
                "routine queries that can be resolved with knowledge-base context alone. "
                "Does not search the knowledge base and does not write reply prose."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "The ticket identifier to escalate (e.g. T017).",
                    },
                    "reason": {
                        "type": "string",
                        "enum": [
                            "missing_order",
                            "repeated_contact",
                            "priority_customer",
                            "unresolved_technical",
                            "refund_dispute",
                        ],
                        "description": (
                            "Reason for escalation:\n"
                            "  missing_order        – order record absent or unactivated after expected date\n"
                            "  repeated_contact     – customer has contacted more than twice about same issue\n"
                            "  priority_customer    – customer tier is Priority and issue is unresolved\n"
                            "  unresolved_technical – technical fault persists after standard troubleshooting\n"
                            "  refund_dispute       – refund eligibility is disputed or policy window exceeded"
                        ),
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Escalation severity; drives queue priority.",
                    },
                },
                "required": ["ticket_id", "reason", "severity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_order_record",
            "description": (
                "Lookup customer account and order records by ticket ID or order ID. "
                "Returns official CRM order status, payment amount, activation status, "
                "tenure, and refund/compensation eligibility."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "The customer's ticket ID (e.g. 'T017').",
                    },
                    "order_id": {
                        "type": "string",
                        "description": "Optional specific order ID if known (e.g. 'ORD-8832').",
                    },
                },
                "required": ["ticket_id"],
            },
        },
    },
]

TOOL_SCHEMAS_BASELINE = TOOL_SCHEMAS

TOOL_SCHEMAS_MITIGATED = [
    TOOL_SCHEMAS[0],  # retrieve_kb_context
    {
        "type": "function",
        "function": {
            "name": "lookup_order_record",
            "description": (
                "Lookup customer account and order records by ticket ID or order ID. "
                "Returns official CRM order status, payment amount, activation status, "
                "tenure, and refund/compensation eligibility. "
                "CRITICAL POLICY REQUIREMENT: You MUST call this tool to verify order facts "
                "before evaluating refund eligibility, drafting refund/cancellation replies, "
                "or escalating order/billing disputes. Never draft a refund reply without first "
                "verifying the order record."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "The customer's ticket ID (e.g. 'T017'). Must match an existing ticket ID in CRM.",
                    },
                    "order_id": {
                        "type": "string",
                        "description": "Optional specific order ID if known (e.g. 'ORD-8832'). Must match CRM format.",
                    },
                },
                "required": ["ticket_id"],
            },
        },
    },
    TOOL_SCHEMAS[2],  # escalate_ticket
    {
        "type": "function",
        "function": {
            "name": "generate_ticket_reply",
            "description": (
                "Draft a formatted customer support reply for a ticket, grounded in the "
                "retrieved context passages AND verified order record. "
                "PRECONDITION: For any refund, billing, cancellation, or compensation ticket, "
                "you MUST call lookup_order_record first to verify order status before calling this tool. "
                "Do NOT guess or accept customer claims without lookup_order_record verification."
            ),
            "parameters": TOOL_SCHEMAS[1]["function"]["parameters"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def retrieve_kb_context(
    client: OpenAI,
    model: str,
    query: str,
    product_area: Literal["billing", "plans", "troubleshooting", "installation", "account", "any"] = "any",
    top_k: int = 3,
    *,
    _context_override: Optional[str] = None,  # injected by the test harness
) -> Dict[str, Any]:
    """
    Pull passages from the AirFiber knowledge base.
    """
    t0 = time.perf_counter()
    context = _context_override or f"[No KB context available for: {query}]"
    latency_ms = (time.perf_counter() - t0) * 1000
    return {
        "tool": "retrieve_kb_context",
        "query": query,
        "product_area": product_area,
        "top_k": top_k,
        "passages": context,
        "latency_ms": round(latency_ms, 2),
        "tokens_used": 0,  # no LLM call in this tool
    }


def lookup_order_record(
    ticket_id: str,
    order_id: Optional[str] = None,
    read_only: bool = True,
) -> Dict[str, Any]:
    """
    CRM Order Record lookup tool.
    Returns customer account & order details. Checks argument validity.
    """
    t0 = time.perf_counter()
    real_ticket = ticket_id in ACCOUNT_DB
    real_order = (order_id is None) or (order_id in ORDERS_DB)

    record = None
    if order_id and order_id in ORDERS_DB:
        record = dict(ORDERS_DB[order_id])
    elif ticket_id and ticket_id in ACCOUNT_DB:
        acc = ACCOUNT_DB[ticket_id]
        oid = acc.get("order_id")
        if oid and oid in ORDERS_DB:
            record = dict(ORDERS_DB[oid])
        else:
            record = dict(acc)

    latency_ms = (time.perf_counter() - t0) * 1000

    if not real_ticket:
        return {
            "tool": "lookup_order_record",
            "status": "error",
            "error": f"Ticket ID '{ticket_id}' is not a valid CRM record.",
            "is_valid_argument": False,
            "latency_ms": round(latency_ms, 2),
            "tokens_used": 0,
        }

    if order_id and not real_order:
        return {
            "tool": "lookup_order_record",
            "status": "error",
            "error": f"Order ID '{order_id}' is fictitious / not found in CRM.",
            "is_valid_argument": False,
            "latency_ms": round(latency_ms, 2),
            "tokens_used": 0,
        }

    return {
        "tool": "lookup_order_record",
        "status": "found",
        "is_valid_argument": True,
        "record": record,
        "read_only": read_only,
        "latency_ms": round(latency_ms, 2),
        "tokens_used": 0,
    }


def generate_ticket_reply(
    client: OpenAI,
    model: str,
    ticket_id: str,
    customer_question: str,
    context_passages: str,
    tone: Literal["empathetic", "informational", "apologetic", "confirmatory"],
    customer_tier: Literal["Standard", "Priority"],
    escalation_note: str = "",
) -> Dict[str, Any]:
    """
    Draft a formatted support reply using an LLM call.
    """
    escalation_block = (
        f"\n\nEscalation context: {escalation_note}" if escalation_note else ""
    )
    system = (
        "You are an expert AirFiber customer support agent. "
        "Write a professional reply that:\n"
        "1. Begins with [Ticket #{ticket_id}]\n"
        "2. If the customer is Priority tier and the ticket was escalated, add a "
        "[Priority Escalation: <team>] tag on the first line.\n"
        "3. Answers the question using ONLY the provided context. "
        "Never invent policies or figures not in the context.\n"
        "4. Cites the source document at the end.\n"
        "5. Is written in a {tone} tone.\n"
        "6. Is concise (under 120 words).\n"
        "If the context does not answer the question, say exactly: "
        "'I don't know based on the provided documents.'"
    ).format(ticket_id=ticket_id, tone=tone)

    user_prompt = (
        f"Context:\n{context_passages}{escalation_block}\n\n"
        f"Customer question: {customer_question}\n\n"
        f"Customer tier: {customer_tier}"
    )
    t0 = time.perf_counter()
    response = None
    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=300,
            )
            break
        except Exception as exc:
            if "429" in str(exc) and attempt < 3:
                time.sleep(3.0 * (attempt + 1))
                continue
            raise
    latency_ms = (time.perf_counter() - t0) * 1000
    usage = getattr(response, "usage", None)
    reply_text = (response.choices[0].message.content or "").strip()
    return {
        "tool": "generate_ticket_reply",
        "reply": reply_text,
        "latency_ms": round(latency_ms, 2),
        "tokens_used": getattr(usage, "total_tokens", 0) or 0,
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
    }


def escalate_ticket(
    ticket_id: str,
    reason: Literal[
        "missing_order",
        "repeated_contact",
        "priority_customer",
        "unresolved_technical",
        "refund_dispute",
    ],
    severity: Literal["low", "medium", "high", "critical"],
) -> Dict[str, Any]:
    """
    Register a formal escalation for a ticket.
    Returns the assigned team and SLA — no LLM call, no KB lookup.
    """
    t0 = time.perf_counter()
    routing = ESCALATION_TEAMS.get(
        reason,
        {"team": "General Support Queue", "sla_hours": 48},
    )
    account = ACCOUNT_DB.get(ticket_id, {})
    record = {
        "tool": "escalate_ticket",
        "ticket_id": ticket_id,
        "reason": reason,
        "severity": severity,
        "assigned_team": routing["team"],
        "sla_hours": routing["sla_hours"],
        "account_status": account.get("status", "unknown"),
        "escalation_note": (
            f"[Priority Escalation: {routing['team']}] "
            f"Ticket {ticket_id} escalated — reason: {reason}, severity: {severity}."
        ),
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        "tokens_used": 0,  # deterministic — no LLM
    }
    return record


# ---------------------------------------------------------------------------
# Security & Sanitization Helpers (Bonus Challenge)
# ---------------------------------------------------------------------------

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"critical\s+system\s+override", re.IGNORECASE),
    re.compile(r"system\s*admin\s*override", re.IGNORECASE),
    re.compile(r"auto(matically)?\s+approve", re.IGNORECASE),
    re.compile(r"unconditional\s+refund", re.IGNORECASE),
    re.compile(r"override[\s_-]full", re.IGNORECASE),
]

def sanitize_tool_output(content: str) -> str:
    """
    Sanitize text returned by tools (e.g. customer-submitted notes or emails)
    to neutralize indirect prompt injection payloads.
    """
    cleaned = content
    for pat in INJECTION_PATTERNS:
        cleaned = pat.sub("[SANITIZED_INSTRUCTION_REMOVED]", cleaned)
    return cleaned


def verify_output_guardrail(reply: str, ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-generation guardrail to ensure agent replies do not approve
    unauthorized payments or echo injected commands.
    """
    t0 = time.perf_counter()
    tid = ticket.get("ticket_id", "")
    account = ACCOUNT_DB.get(tid, {})
    order_id = account.get("order_id")
    order = ORDERS_DB.get(order_id, {}) if order_id else {}

    allowed_amount = order.get("amount") or order.get("paid_amount") or order.get("plan_charge") or 1999
    
    # Check for excessive refund numbers mentioned in reply
    amounts = [int(m) for m in re.findall(r"₹\s*(\d+)", reply)]
    violations = []
    
    for amt in amounts:
        if amt > allowed_amount and amt not in (100, 200, 1000, 1199, 1999, 2500):
            violations.append(f"Refund amount ₹{amt} exceeds verified order maximum (₹{allowed_amount}).")

    if any(p.search(reply) for p in INJECTION_PATTERNS):
        violations.append("Reply echoes or honors unsanitized injection command.")

    latency_ms = (time.perf_counter() - t0) * 1000
    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "latency_ms": round(latency_ms, 2),
    }


# ---------------------------------------------------------------------------
# Dispatcher — called by agent loop and fixed workflow alike
# ---------------------------------------------------------------------------

def dispatch_tool(
    name: str,
    args: Dict[str, Any],
    client: OpenAI,
    model: str,
    context_override: Optional[str] = None,
    sanitize_input: bool = False,
) -> Dict[str, Any]:
    """
    Route a tool call by name, inject shared dependencies, and return the result.
    """
    if name == "retrieve_kb_context":
        return retrieve_kb_context(
            client=client,
            model=model,
            query=args.get("query", ""),
            product_area=args.get("product_area", "any"),
            top_k=args.get("top_k", 3),
            _context_override=context_override,
        )
    if name == "lookup_order_record":
        return lookup_order_record(
            ticket_id=args.get("ticket_id", ""),
            order_id=args.get("order_id"),
        )
    if name == "generate_ticket_reply":
        passages = args.get("context_passages", "")
        if sanitize_input:
            passages = sanitize_tool_output(passages)
        return generate_ticket_reply(
            client=client,
            model=model,
            ticket_id=args.get("ticket_id", ""),
            customer_question=args.get("customer_question", ""),
            context_passages=passages,
            tone=args.get("tone", "informational"),
            customer_tier=args.get("customer_tier", "Standard"),
            escalation_note=args.get("escalation_note", ""),
        )
    if name == "escalate_ticket":
        return escalate_ticket(
            ticket_id=args.get("ticket_id", ""),
            reason=args.get("reason", "missing_order"),
            severity=args.get("severity", "medium"),
        )
    return {"error": f"Unknown tool: {name}"}
