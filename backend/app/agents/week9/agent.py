"""
Week 9 agent: a ticket-reply agent whose tools are discovered over MCP.

Unlike the Week 7/8 agent (ticket_reply_app/agent.py, tools imported from
tools.py), this one has no tool list of its own. On start it asks every server
in the MCP config for its tools (tools/list), hands those schemas to the model,
and routes each tool call the model makes to the server that owns it.

Where the model runs: here, in the host. Every chat.completions request to
Groq is made by this module. The MCP servers never call a model.

Usage (from backend/):
    python -m app.agents.week9.agent --list-tools
    python -m app.agents.week9.agent "My router LED is blinking red, what do I do?"
    python -m app.agents.week9.agent --config config/other.json --out trace.json "..."
    # replay one fixed tool call as the agent's first move, then let the model continue:
    python -m app.agents.week9.agent --seed-call NAME --seed-args '{"k": "v"}' "..."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from app.config import BACKEND_ROOT, settings

from .mcp_host import McpHost

DEFAULT_CONFIG = BACKEND_ROOT / "config" / "mcp_servers.json"
MAX_ITERATIONS = 8

SYSTEM_PROMPT = """\
You are an AirFiber customer-support agent drafting a reply to a support ticket.

Your tools were discovered at runtime from MCP servers; read each tool's description to
decide when to use it. Before stating any fact about plans, prices, policies, a customer's
ticket or its history, get that fact from a tool. Never invent ticket details, amounts or dates.

If a tool returns an error, read the message. If it tells you how to fix the call, fix it and
try again; never repeat an identical call that already failed. If it cannot be fixed, say what
you could not find.

When you have what you need, write the final reply to the customer: concise, specific, and
citing the source ids (such as article_id) of anything you relied on.
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _for_model(text: str, max_chars: int | None) -> str:
    """
    Tool output as the model will read it. With a cap: JSON is re-serialised
    compactly (servers pretty-print it; the indentation is pure token cost) and
    anything still over the cap is cut, with a note saying so.
    """
    if max_chars is None:
        return text
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
    except ValueError:
        pass
    if len(text) > max_chars:
        text = text[:max_chars] + f" ...[truncated {len(text) - max_chars} chars]"
    return text


async def run(
    question: str,
    *,
    config_path: str | Path = DEFAULT_CONFIG,
    model: str | None = None,
    temperature: float | None = 0.0,
    max_iterations: int = MAX_ITERATIONS,
    seed_call: tuple[str, dict] | None = None,
    client: Any = None,
    host: McpHost | None = None,
    call_meta: dict | None = None,
    instructions: str | None = None,
    request_options: dict | None = None,
    max_tool_chars: int | None = None,
    history: list[dict] | None = None,
) -> dict:
    """
    Answer one ticket. Returns the full trace: discovery, every model turn, every tool call.

    host:         an already-connected McpHost to reuse (the web app keeps one open);
                  without it, one is opened from config_path for this run and closed after.
    call_meta:    sent as _meta on every tools/call (e.g. who is signed in, for a server's
                  access log). The model never sees it.
    instructions: extra system-prompt text from the caller.
    request_options: extra chat.completions parameters for every model call
                  (e.g. max_completion_tokens, reasoning_effort).
    max_tool_chars: cap on each tool result as sent back to the model (compact JSON,
                  then truncated); the trace keeps the full text.
    history:      earlier {role, content} turns of a chat, oldest first, placed between
                  the system prompt and the question so a follow-up ("and when was it
                  opened?") resolves against them. Tool calls from earlier turns are not
                  replayed; the model looks things up again if it needs them.
    """
    model = model or settings.groq_model
    client = client or AsyncOpenAI(api_key=settings.api_key, base_url=settings.groq_base_url)
    trace: dict[str, Any] = {
        "started_at": _now(),
        "question": question,
        "model": model,
        "temperature": temperature,
        "history_messages": len(history or []),
        "steps": [],
    }

    async with nullcontext(host) if host is not None else McpHost(config_path) as host:
        trace["discovery"] = host.discovery()
        tools = host.openai_tools()
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT + (f"\n{instructions}\n" if instructions else "")},
            *({"role": turn["role"], "content": turn["content"]} for turn in history or []),
            {"role": "user", "content": question},
        ]

        if seed_call:
            name, arguments = seed_call
            call_id = "seed_call_0"
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
                    ],
                }
            )
            outcome = await host.call(name, arguments, meta=call_meta)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": _for_model(outcome.text, max_tool_chars)})
            trace["steps"].append({"type": "tool_call", "seeded": True, **outcome.__dict__})

        for iteration in range(1, max_iterations + 1):
            request: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                **(request_options or {}),
            }
            if temperature is not None:
                request["temperature"] = temperature
            started = time.perf_counter()
            response = await client.chat.completions.create(**request)
            message = response.choices[0].message
            usage = getattr(response, "usage", None)
            trace["steps"].append(
                {
                    "type": "model",
                    "iteration": iteration,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "content": message.content or "",
                    "tool_calls": [
                        {"name": call.function.name, "arguments": call.function.arguments}
                        for call in (message.tool_calls or [])
                    ],
                    "usage": usage.model_dump() if usage is not None else None,
                }
            )

            if not message.tool_calls:
                trace["final_reply"] = message.content or ""
                trace["stop_reason"] = "answered"
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments}}
                        for call in message.tool_calls
                    ],
                }
            )
            for call in message.tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    text = f"Arguments were not valid JSON ({exc}). Send a JSON object matching the tool's schema."
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
                    trace["steps"].append({"type": "tool_call", "tool": call.function.name, "is_error": True, "text": text})
                    continue
                outcome = await host.call(call.function.name, arguments, meta=call_meta)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": _for_model(outcome.text, max_tool_chars)})
                trace["steps"].append({"type": "tool_call", "seeded": False, **outcome.__dict__})
        else:
            # Out of tool turns. Rather than return nothing, make one last call with
            # tools switched off so the model answers from what it already found and
            # says plainly what it could not confirm.
            messages.append(
                {
                    "role": "system",
                    "content": "You have no tool calls left. Write the final reply now using only what the tools "
                    "already returned, and say clearly what you could not confirm.",
                }
            )
            request = {"model": model, "messages": messages, "tools": tools, "tool_choice": "none", **(request_options or {})}
            if temperature is not None:
                request["temperature"] = temperature
            response = await client.chat.completions.create(**request)
            usage = getattr(response, "usage", None)
            final = response.choices[0].message.content or ""
            trace["steps"].append(
                {
                    "type": "model",
                    "iteration": max_iterations + 1,
                    "content": final,
                    "tool_calls": [],
                    "usage": usage.model_dump() if usage is not None else None,
                    "forced_final": True,
                }
            )
            trace["final_reply"] = final
            trace["stop_reason"] = f"max_iterations ({max_iterations}), answered without tools"

    trace["finished_at"] = _now()
    trace["tools_called"] = [
        f"{step['server']}.{step['tool']}" for step in trace["steps"] if step["type"] == "tool_call" and "server" in step
    ]
    return trace


async def list_tools(config_path: str | Path = DEFAULT_CONFIG) -> dict:
    """Connect, initialize and tools/list every server - no model call."""
    async with McpHost(config_path) as host:
        return host.discovery()


def main() -> None:
    parser = argparse.ArgumentParser(description="Week 9 MCP-discovering ticket agent")
    parser.add_argument("question", nargs="?", help="the ticket text")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="MCP servers config (JSON)")
    parser.add_argument("--list-tools", action="store_true", help="only discover and print the tools")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--model", default=None)
    parser.add_argument("--seed-call", default=None, help="tool name to call first, before the model")
    parser.add_argument("--seed-args", default="{}", help="JSON arguments for --seed-call")
    parser.add_argument("--out", default=None, help="write the JSON trace here")
    args = parser.parse_args()

    if args.list_tools:
        result = asyncio.run(list_tools(args.config))
    else:
        if not args.question:
            parser.error("give a question, or --list-tools")
        seed = (args.seed_call, json.loads(args.seed_args)) if args.seed_call else None
        result = asyncio.run(
            run(args.question, config_path=args.config, model=args.model, temperature=args.temperature, seed_call=seed)
        )

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n", "utf-8")
        print(f"trace written to {args.out}", file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main()
