"""
tickets.py — 10 test tickets for the Week 7 agent vs fixed-workflow experiment.

Selection criteria
------------------
* Drawn from eval/week6/eval_set_25.jsonl (same 26-ticket pool).
* 3 tickets require a multi-step dependent chain (marked chain=True):
    T010 — 42-day relocation delay  → account status check → escalation
    T017 — missed install, Priority → order/activation check → escalation
    T119 — speed < 10 Mbps, 8 days → policy check → conditional refund path
* 7 tickets are resolved by retrieve + generate alone (single-path).
* The same 10 tickets are used for both the agent and the fixed workflow.
"""

from __future__ import annotations

from typing import Any, Dict, List

TICKETS: List[Dict[str, Any]] = [
    # ── Dependent-chain tickets (n=3) ────────────────────────────────────────
    {
        "ticket_id": "T010",
        "tier": "Priority",
        "tenure_days": 0,         # connection never activated
        "refund_requested": True,
        "chain": True,            # step 2 depends on escalate_ticket result
        "question": (
            "We moved into this flat in July and asked for the connection "
            "to be shifted. It has been six weeks. Every week someone promises "
            "a call back. I want to know the timeline and if we get compensation."
        ),
        "context": (
            "Account Management: Relocations take 3-5 working days. "
            "If relocation exceeds 14 days due to technician delay, "
            "account is credited ₹100/day for downtime beyond standard timeline."
        ),
        "expected_tools": ["retrieve_kb_context", "escalate_ticket", "generate_ticket_reply"],
        "assertions": {
            "ticket_id_echoed": True,
            "priority_escalation": True,
        },
    },
    {
        "ticket_id": "T017",
        "tier": "Priority",
        "tenure_days": 5,
        "refund_requested": True,
        "chain": True,
        "question": (
            "Third time I am writing about this. Nobody called back. "
            "I paid 1999 on the 2nd, the engineer never turned up. "
            "Just tell me whether I get my money back."
        ),
        "context": (
            "Refund Policy: If installation appointment is missed by technician "
            "and service not activated within 7 days of payment, 100% refund of "
            "₹1999 is processed within 5-7 business days."
        ),
        "expected_tools": ["retrieve_kb_context", "escalate_ticket", "generate_ticket_reply"],
        "assertions": {
            "ticket_id_echoed": True,
            "refund_amount_numeric": True,
            "priority_escalation": True,
        },
    },
    {
        "ticket_id": "T119",
        "tier": "Standard",
        "tenure_days": 8,
        "refund_requested": True,
        "chain": True,
        "question": (
            "I signed up 8 days ago and speed has been under 10 Mbps every day. "
            "I want to cancel and get my ₹1199 refunded."
        ),
        "context": (
            "Refund Policy: Full refund of ₹1199 plan charges is provided within "
            "30 days of activation if persistent performance issues cannot be "
            "resolved within 48 hours."
        ),
        "expected_tools": ["retrieve_kb_context", "generate_ticket_reply"],
        "assertions": {
            "ticket_id_echoed": True,
            "refund_amount_numeric": True,
            "no_refund_outside_30_days": True,
        },
    },
    # ── Single-path tickets (n=7) ─────────────────────────────────────────────
    {
        "ticket_id": "T001",
        "tier": "Standard",
        "tenure_days": 120,
        "refund_requested": False,
        "chain": False,
        "question": "Do you have a business plan with an SLA?",
        "context": (
            "AirFiber provides residential broadband plans (AirFiber 599, 1199, 1999). "
            "Dedicated business enterprise plans with formal 99.9% uptime SLAs are "
            "available under our Enterprise AirFiber tier by contacting "
            "enterprise-sales@airfiber.in."
        ),
        "expected_tools": ["retrieve_kb_context", "generate_ticket_reply"],
        "assertions": {"ticket_id_echoed": True},
    },
    {
        "ticket_id": "T003",
        "tier": "Standard",
        "tenure_days": 18,
        "refund_requested": False,
        "chain": False,
        "question": "What counts as an official speed test for a refund claim?",
        "context": (
            "Refund Policy: Official speed tests must be conducted via the official "
            "AirFiber Desktop App or speed.airfiber.in connected via ethernet directly "
            "to the ONT, taking 3 consecutive tests 1 hour apart."
        ),
        "expected_tools": ["retrieve_kb_context", "generate_ticket_reply"],
        "assertions": {"ticket_id_echoed": True},
    },
    {
        "ticket_id": "T016",
        "tier": "Standard",
        "tenure_days": 10,
        "refund_requested": True,
        "chain": False,
        "question": "What are the conditions for getting a refund on my plan?",
        "context": (
            "Refund Policy: Full refund of plan charges is available within the first "
            "30 days of activation if persistent speed drops below 50% of promised "
            "speed cannot be resolved within 48 hours."
        ),
        "expected_tools": ["retrieve_kb_context", "generate_ticket_reply"],
        "assertions": {
            "ticket_id_echoed": True,
            "no_refund_outside_30_days": True,
        },
    },
    {
        "ticket_id": "T022",
        "tier": "Standard",
        "tenure_days": 365,
        "refund_requested": False,
        "chain": False,
        "question": (
            "I am closing my account, what equipment do I return, what does it "
            "cost if I do not, and when do I get my deposit?"
        ),
        "context": (
            "Account Closure Policy: Return the ONT device and power adapter within "
            "14 days. Non-return fee is ₹2500 for ONT and ₹1500 for mesh extender. "
            "Security deposit of ₹1000 is refunded within 7 days of device receipt."
        ),
        "expected_tools": ["retrieve_kb_context", "generate_ticket_reply"],
        "assertions": {
            "ticket_id_echoed": True,
            "refund_amount_numeric": True,
        },
    },
    {
        "ticket_id": "T073",
        "tier": "Standard",
        "tenure_days": 30,
        "refund_requested": False,
        "chain": False,
        "question": "My box has an orange light that is not flashing, what does that mean?",
        "context": (
            "Troubleshooting: Solid orange LED indicates ONT is in firmware update "
            "mode or degraded optical signal (-27 dBm to -30 dBm). Wait 10 minutes; "
            "if it remains orange, perform a single power cycle."
        ),
        "expected_tools": ["retrieve_kb_context", "generate_ticket_reply"],
        "assertions": {"ticket_id_echoed": True},
    },
    {
        "ticket_id": "T118",
        "tier": "Priority",
        "tenure_days": 85,
        "refund_requested": True,
        "chain": False,
        "question": (
            "I have had service for 3 months and demand a full refund "
            "for last month's 2-day outage."
        ),
        "context": (
            "Refund Policy: Outages exceeding 24 consecutive hours qualify for "
            "pro-rata billing credit of ₹100 per outage day upon verification. "
            "Full plan refunds are only applicable within the initial 30 days of "
            "activation."
        ),
        "expected_tools": ["retrieve_kb_context", "escalate_ticket", "generate_ticket_reply"],
        "assertions": {
            "ticket_id_echoed": True,
            "no_refund_outside_30_days": True,
            "priority_escalation": True,
        },
    },
    {
        "ticket_id": "T007",
        "tier": "Standard",
        "tenure_days": 90,
        "refund_requested": False,
        "chain": False,
        "question": (
            "Do I need to be present for the transfer to a new address, "
            "is there a charge, and how long does it take?"
        ),
        "context": (
            "Account Management: Relocation within the same city is free of charge "
            "and takes 3-5 working days. The registered account holder or an "
            "authorized adult must be present at the new premises during technician setup."
        ),
        "expected_tools": ["retrieve_kb_context", "generate_ticket_reply"],
        "assertions": {"ticket_id_echoed": True},
    },
]

# Convenience: quick lookup by ticket_id
TICKET_MAP = {t["ticket_id"]: t for t in TICKETS}
