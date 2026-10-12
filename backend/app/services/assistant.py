"""
The web assistant: the Week 9 MCP agent behind the chat UI.

One McpHost is opened when the server starts and kept for its whole life, so a
question does not pay to spawn servers. Its config (config/mcp_servers.webapp.json)
runs the help-centre server in-process - it then searches this app's own live
index, so an admin upload is visible immediately - and the ticket-history server
as a stdio subprocess, exactly as the Week 9 CLI agent does.

Any signed-in user may ask about the help centre and about any ticket; there is
no per-customer scoping. The signed-in user is still sent to every tools/call as
_meta so the ticket server's access log records who asked.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import openai

from app.agents.week9 import agent as week9_agent
from app.agents.week9.mcp_host import McpHost
from app.config import settings
from app.services import follow_up
from app.services.auth import AuthUser

logger = logging.getLogger(__name__)

WEB_INSTRUCTIONS = """\
You are answering a person live in the AirFiber support chat, not drafting an email. Reply
directly to them, short and plain. They may ask about the help centre (plans, billing,
refunds, installation, connection problems) or about a support ticket. When a ticket is
mentioned, look it up before saying anything about it; if they describe a ticket without
its id, find it first instead of guessing.

You can only look information up. Never promise or claim an action - a callback, a refund,
a reschedule, "I'll follow up", "I've escalated it" - because no tool can do any of that; say
instead what the record shows and what the person can do next. Do not show tool names or
bracketed citation marks such as 【...】; when you used a help article, mention its id in plain
words (e.g. "see KB-004").
"""


# Groq's free tier allows 8,000 tokens per minute, and it counts each request's
# prompt PLUS its maximum possible completion. An agent resends the whole
# conversation every turn, so a few help-centre searches can push one request
# past the limit (HTTP 413) or several past it within a minute (slow retries).
MAX_ITERATIONS = 4            # tool turns per question (the CLI agent allows 8)
MAX_TOOL_CHARS = 2500         # each tool result as the model reads it
REQUEST_OPTIONS = {
    "max_completion_tokens": 1024,  # caps what Groq reserves against the per-minute limit
    "reasoning_effort": "low",      # gpt-oss: fewer hidden reasoning tokens, faster turns
}


class AssistantUnavailable(RuntimeError):
    pass


class AssistantBusy(RuntimeError):
    """Groq refused the request for size or rate; worth retrying shortly."""


class Assistant:
    def __init__(self) -> None:
        self.host: McpHost | None = None
        self.error: str | None = None

    @property
    def ready(self) -> bool:
        return self.host is not None

    async def start(self) -> None:
        host = McpHost(settings.resolved_assistant_config)
        try:
            await host.__aenter__()
        except Exception as exc:  # a broken MCP server must not take the whole app down
            self.error = f"{type(exc).__name__}: {exc}"
            logger.warning("Assistant MCP servers failed to start: %s", self.error)
            return
        self.host = host
        self.error = None
        await asyncio.to_thread(_warm_up)
        discovery = host.discovery()
        logger.info("Assistant ready: %d MCP tools %s", discovery["tool_count"], discovery["tool_names"])

    async def stop(self) -> None:
        if self.host is not None:
            host, self.host = self.host, None
            await host.__aexit__(None, None, None)

    def discovery(self) -> dict:
        if self.host is None:
            raise AssistantUnavailable(self.error or "The assistant is not running.")
        return self.host.discovery()

    async def ask(self, message: str, user: AuthUser, history: list | None = None) -> dict:
        if self.host is None:
            raise AssistantUnavailable(self.error or "The assistant is not running.")
        temperature = settings.groq_temperature if settings.groq_temperature is not None else 0.0
        try:
            trace = await week9_agent.run(
                message,
                host=self.host,
                call_meta={"caller": {"username": user.username, "role": user.role}},
                instructions=WEB_INSTRUCTIONS,
                model=settings.assistant_model.strip() or None,
                temperature=temperature,
                max_iterations=MAX_ITERATIONS,
                request_options=REQUEST_OPTIONS,
                max_tool_chars=MAX_TOOL_CHARS,
                history=follow_up.trim_history(history),
            )
        except openai.APIStatusError as exc:
            if exc.status_code in (413, 429):
                raise AssistantBusy(
                    "The assistant is handling too many requests right now (Groq rate limit). "
                    "Please wait about a minute and ask again."
                ) from exc
            raise
        return _response(trace)


def _warm_up() -> None:
    """Load the cross-encoder now, so the first customer question doesn't wait ~8 s for it."""
    try:
        from app.services.rag_service import get_rag_service

        get_rag_service().retrieve("warm up", top_k=1, mode="week4")
    except Exception as exc:
        logger.warning("Assistant warm-up skipped: %s", exc)


def _response(trace: dict) -> dict:
    tool_calls, sources, tickets = [], [], []
    seen_sources: set[tuple] = set()
    for step in trace["steps"]:
        if step["type"] != "tool_call" or "server" not in step:
            continue
        tool_calls.append(
            {
                "server": step["server"],
                "tool": step["tool"],
                "arguments": step.get("arguments") or {},
                "is_error": step["is_error"],
                "latency_ms": step.get("latency_ms"),
            }
        )
        if step["is_error"]:
            continue
        try:
            payload = json.loads(step["text"])
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        passages = payload.get("passages")
        if passages is None and payload.get("article_id") and payload.get("text"):
            passages = [{**payload, "section": payload.get("title", "")}]
        for passage in passages or []:
            key = (passage.get("article_id"), passage.get("section"))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            sources.append(
                {
                    "article_id": passage.get("article_id", ""),
                    "source_file": passage.get("source_file", ""),
                    "section": passage.get("section", ""),
                    "product_area": passage.get("product_area", ""),
                    "preview": (passage.get("text") or "")[:280],
                }
            )
        ticket_id = payload.get("ticket_id")
        if isinstance(ticket_id, str) and ticket_id not in tickets:
            tickets.append(ticket_id)

    turns = [s for s in trace["steps"] if s["type"] == "model"]
    follow_ups: list[dict] = []
    if sources:
        try:
            from app.services.rag_service import get_rag_service

            follow_ups = get_rag_service().suggest_follow_ups(
                [(source["article_id"], source["section"]) for source in sources]
            )
        except Exception as exc:  # suggestions are a nicety; the answer stands without them
            logger.warning("Follow-up suggestions skipped: %s", exc)
    return {
        "answer": trace.get("final_reply", ""),
        "tool_calls": tool_calls,
        "sources": sources,
        "tickets": tickets,
        "stop_reason": trace.get("stop_reason", ""),
        "model_turns": len(turns),
        "total_tokens": sum((s.get("usage") or {}).get("total_tokens", 0) for s in turns),
        "follow_ups": follow_ups,
    }


_assistant = Assistant()


def get_assistant() -> Assistant:
    return _assistant
