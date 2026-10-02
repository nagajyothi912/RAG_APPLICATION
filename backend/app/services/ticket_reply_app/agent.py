"""
agent.py — ReAct agent loop with 4 safety budgets.

The agent receives a ticket and decides autonomously which tools to call and
in which order by interpreting the LLM's tool_choice responses. It stops when:
  • the LLM returns a final text answer (no pending tool calls), OR
  • any of the 4 safety budgets is exhausted (clean termination, not an error).

Safety budgets
--------------
  MAX_ITERATIONS : Maximum number of agent loop iterations per ticket.
  MAX_TOKENS     : Cumulative token ceiling across all LLM calls for one ticket.
  MAX_COST_USD   : Cost ceiling (USD) across all LLM calls for one ticket.
  MAX_WALL_CLOCK : Wall-clock time ceiling (seconds) for the entire ticket run.

When a budget fires, the agent sets `budget_hit` in its result and returns
immediately with whatever reply has been assembled so far (or an explicit note).
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from .tools import TOOL_SCHEMAS, dispatch_tool

# ---------------------------------------------------------------------------
# Budget defaults (can be overridden per-run)
# ---------------------------------------------------------------------------
MAX_ITERATIONS: int   = 8
MAX_TOKENS: int       = 15000   # raised: 120B model uses ~1500-8000 tokens/ticket
MAX_COST_USD: float   = 0.10
MAX_WALL_CLOCK: float = 60.0  # seconds

# Cost per token for openai/gpt-oss-120b on Groq (USD per token)
# Source: Groq pricing page — $0.09 / 1M input, $0.09 / 1M output
INPUT_COST_PER_TOKEN:  float = 0.09 / 1_000_000
OUTPUT_COST_PER_TOKEN: float = 0.09 / 1_000_000


# ---------------------------------------------------------------------------
# Budget tracker
# ---------------------------------------------------------------------------

class BudgetTracker:
    def __init__(
        self,
        max_iterations: int   = MAX_ITERATIONS,
        max_tokens: int       = MAX_TOKENS,
        max_cost_usd: float   = MAX_COST_USD,
        max_wall_clock: float = MAX_WALL_CLOCK,
    ) -> None:
        self.max_iterations  = max_iterations
        self.max_tokens      = max_tokens
        self.max_cost_usd    = max_cost_usd
        self.max_wall_clock  = max_wall_clock
        self.iterations: int  = 0
        self.total_tokens: int = 0
        self.total_cost: float = 0.0
        self._start: float    = time.perf_counter()

    def add_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.total_tokens += prompt_tokens + completion_tokens
        self.total_cost   += (
            prompt_tokens     * INPUT_COST_PER_TOKEN
            + completion_tokens * OUTPUT_COST_PER_TOKEN
        )

    def elapsed(self) -> float:
        return time.perf_counter() - self._start

    def check(self) -> Optional[str]:
        """Return the name of the first budget that is exhausted, else None."""
        if self.iterations >= self.max_iterations:
            return "max_iterations"
        if self.total_tokens >= self.max_tokens:
            return "max_tokens"
        if self.total_cost >= self.max_cost_usd:
            return "max_cost"
        if self.elapsed() >= self.max_wall_clock:
            return "max_wall_clock"
        return None

    def config(self) -> Dict[str, Any]:
        return {
            "max_iterations":  self.max_iterations,
            "max_tokens":      self.max_tokens,
            "max_cost_usd":    self.max_cost_usd,
            "max_wall_clock_s": self.max_wall_clock,
        }


# ---------------------------------------------------------------------------
# System prompt for the agent
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """\
You are an AirFiber customer support agent. Resolve each support ticket by
calling the available tools in the appropriate order:

1. Call retrieve_kb_context to fetch relevant policy or help-centre content.
2. If the ticket requires formal escalation (Priority tier unresolved, missed
   orders, repeated contact, or technical faults after troubleshooting),
   call escalate_ticket with the correct reason and severity.
3. Call generate_ticket_reply with the retrieved context (and the escalation
   note when applicable) to draft the final reply.

Rules:
- Use tools; do NOT write the reply yourself without calling generate_ticket_reply.
- Call escalate_ticket ONLY when the situation genuinely warrants it.
- If a previous tool call returns an error or unexpected result, adapt your plan.
- When all needed tool calls are done, call generate_ticket_reply and then stop.
"""


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_agent(
    ticket: Dict[str, Any],
    client: OpenAI,
    model: str,
    budget: Optional[BudgetTracker] = None,
) -> Dict[str, Any]:
    """
    Run the ReAct agent on one ticket.

    Returns a result dict with:
        reply          : str  — the final drafted reply (or partial if budget hit)
        tools_called   : list — ordered sequence of tool names invoked
        tool_results   : list — full result dict from each tool call
        iterations     : int
        total_tokens   : int
        total_cost_usd : float
        latency_ms     : float
        budget_hit     : str | None — which budget fired, if any
        budget_config  : dict
        messages       : list — full conversation for audit
    """
    if budget is None:
        budget = BudgetTracker()

    wall_start   = time.perf_counter()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Ticket ID: {ticket['ticket_id']}\n"
                f"Customer tier: {ticket['tier']}\n"
                f"Customer question: {ticket['question']}"
            ),
        },
    ]
    tools_called: List[str] = []
    tool_results: List[Dict[str, Any]] = []
    reply        = ""
    budget_hit   = None

    while True:
        # ── Check all 4 budgets before every iteration ─────────────────────
        budget_hit = budget.check()
        if budget_hit:
            _log_budget_event(ticket, budget_hit, budget)
            break

        budget.iterations += 1

        # ── LLM decides the next action ─────────────────────────────────────
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=512,
            )
        except Exception as exc:
            reply = f"[Agent error: LLM call failed — {exc}]"
            break

        usage = getattr(response, "usage", None)
        p_tok = getattr(usage, "prompt_tokens", 0) or 0
        c_tok = getattr(usage, "completion_tokens", 0) or 0
        budget.add_usage(p_tok, c_tok)

        choice  = response.choices[0]
        message = choice.message

        # Append assistant turn to conversation
        messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id":       tc.id,
                        "type":     "function",
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in (message.tool_calls or [])
                ],
            }
        )

        # ── No tool calls → agent is done ──────────────────────────────────
        if not message.tool_calls:
            reply = (message.content or "").strip()
            break

        # ── Dispatch each tool the LLM requested ──────────────────────────
        for tc in message.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            tools_called.append(name)
            result = dispatch_tool(
                name=name,
                args=args,
                client=client,
                model=model,
                context_override=ticket.get("context"),
            )
            tool_results.append(result)

            # If generate_ticket_reply was called, grab the reply text now
            if name == "generate_ticket_reply" and "reply" in result:
                reply = result["reply"]

            # Feed the tool output back into the conversation
            messages.append(
                {
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "name":         name,
                    "content":      json.dumps(result, ensure_ascii=False),
                }
            )

    latency_ms = (time.perf_counter() - wall_start) * 1000
    return {
        "system":        "agent",
        "ticket_id":     ticket["ticket_id"],
        "reply":         reply,
        "tools_called":  tools_called,
        "tool_results":  tool_results,
        "iterations":    budget.iterations,
        "total_tokens":  budget.total_tokens,
        "total_cost_usd": budget.total_cost,
        "latency_ms":    round(latency_ms, 2),
        "budget_hit":    budget_hit,
        "budget_config": budget.config(),
        "messages":      messages,
    }


# ---------------------------------------------------------------------------
# Budget event logger (clean termination record)
# ---------------------------------------------------------------------------

def _log_budget_event(
    ticket: Dict[str, Any],
    budget_hit: str,
    budget: BudgetTracker,
) -> None:
    """Print a structured budget-termination record to stdout."""
    limits = {
        "max_iterations":  budget.max_iterations,
        "max_tokens":      budget.max_tokens,
        "max_cost":        budget.max_cost_usd,
        "max_wall_clock":  budget.max_wall_clock,
    }
    current = {
        "max_iterations":  budget.iterations,
        "max_tokens":      budget.total_tokens,
        "max_cost":        round(budget.total_cost, 6),
        "max_wall_clock":  round(budget.elapsed(), 2),
    }
    record = {
        "event":           "BUDGET_TERMINATED",
        "ticket_id":       ticket["ticket_id"],
        "budget_hit":      budget_hit,
        "configured_limit": limits.get(budget_hit),
        "current_value":   current.get(budget_hit),
        "all_budgets":     {
            b: {"limit": limits[b], "current": current[b]} for b in limits
        },
        "clean_termination": True,
    }
    print("\n[BUDGET TERMINATION]", json.dumps(record, indent=2))
