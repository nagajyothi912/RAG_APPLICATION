"""
metering.py — One metered LLM client for both arms of the race.

Both arms call Groq through `MeteredClient`, so tokens, cost, and time lost to
rate limits are counted the same way for each. Groq's free tier allows a few
thousand tokens per minute, so a 429 is routine here: the client waits it out
itself and records the wait, which lets the race report latency both as the
customer would see it and with quota waits removed.

The Week 7 agent is used unchanged. It only sees a client with
`.chat.completions.create`, and since this client absorbs the 429s, the agent's
own retry path never fires.
"""

from __future__ import annotations

import contextvars
import math
import re
import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

# openai/gpt-oss-120b on Groq, USD per token. Week 7 used $0.09/$0.09; current
# trackers list $0.15 in / $0.60 out (Groq's launch post said $0.75 out). Both
# arms use the same constants, so the multiplier does not depend on them.
INPUT_COST_PER_TOKEN: float = 0.15 / 1_000_000
OUTPUT_COST_PER_TOKEN: float = 0.60 / 1_000_000

# The hand-off the current LLM call belongs to. Set by whoever makes the call;
# worker threads get a copy of the caller's context.
CURRENT_HOP: contextvars.ContextVar[str] = contextvars.ContextVar("current_hop", default="unlabelled")


class QuotaExhausted(RuntimeError):
    """Groq asked for a wait longer than the race is willing to sit through."""


def call_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return prompt_tokens * INPUT_COST_PER_TOKEN + completion_tokens * OUTPUT_COST_PER_TOKEN


def _is_rate_limit(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 429 or "429" in str(exc)


def retry_after_seconds(exc: Exception) -> float:
    """Seconds Groq asked us to wait, from the header or the message ("try again in 1m2.5s")."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        value = headers.get("retry-after")
        if value:
            return float(value)
    except (TypeError, ValueError):
        pass
    match = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", str(exc))
    if match and any(match.groups()):
        h, m, s = match.groups()
        return int(h or 0) * 3600 + int(m or 0) * 60 + float(s or 0)
    return 5.0


class Ledger:
    """Every LLM call (and every failed hand-off) of one run, in order."""

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def add(self, record: Dict[str, Any]) -> None:
        with self._lock:
            self.records.append(record)

    def extend(self, records: List[Dict[str, Any]]) -> None:
        with self._lock:
            self.records.extend(records)

    @property
    def total_tokens(self) -> int:
        return sum(r["total_tokens"] for r in self.records)

    @property
    def total_cost(self) -> float:
        return sum(r["cost_usd"] for r in self.records)

    @property
    def rate_limit_wait_ms(self) -> float:
        return sum(r["rate_limit_wait_ms"] for r in self.records)


class MeteredClient:
    """Drop-in for `OpenAI` where only `chat.completions.create` is used."""

    def __init__(self, inner: Any, ledger: Optional[Ledger] = None, max_wait_s: float = 120.0) -> None:
        self.inner = inner
        self.ledger = ledger if ledger is not None else Ledger()
        self.max_wait_s = max_wait_s
        self.quota_exhausted = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        hop = CURRENT_HOP.get()
        waited = 0.0
        while True:
            t0 = time.perf_counter()
            try:
                response = self.inner.chat.completions.create(**kwargs)
                break
            except Exception as exc:
                if not _is_rate_limit(exc):
                    # Groq reports no usage on a rejected call, so its tokens
                    # are unknown; the call is still logged so it is not invisible.
                    self.ledger.add({
                        "hop": hop, "kind": "rejected", "status": f"api_{getattr(exc, 'status_code', 'error')}",
                        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
                        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                        "rate_limit_wait_ms": round(waited * 1000, 1),
                        "error": str(getattr(exc, "body", None) or exc)[:200],
                    })
                    raise
                wait = retry_after_seconds(exc) + 0.5
                if wait > self.max_wait_s:
                    # Usually the daily cap. The agent swallows exceptions into
                    # its reply, so the flag is how the race tells this apart
                    # from a genuine failure and refuses to score the run.
                    # The message leaves out the original error text on purpose:
                    # the Week 7 code retries anything whose text says "429".
                    self.quota_exhausted = True
                    raise QuotaExhausted(f"Groq quota: asked to wait {wait:.0f}s") from exc
                time.sleep(wait)
                waited += wait
        latency_ms = (time.perf_counter() - t0) * 1000
        usage = getattr(response, "usage", None)
        p_tok = getattr(usage, "prompt_tokens", 0) or 0
        c_tok = getattr(usage, "completion_tokens", 0) or 0
        self.ledger.add({
            "hop": hop,
            "kind": "tool-calling" if kwargs.get("tools") else "completion",
            "status": "ok",
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_tokens": p_tok + c_tok,
            "cost_usd": call_cost(p_tok, c_tok),
            "latency_ms": round(latency_ms, 1),
            "rate_limit_wait_ms": round(waited * 1000, 1),
        })
        return response


def percentile(values: List[float], pct: float) -> float:
    """Nearest-rank percentile. With 10 values, p99 is the slowest one."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]
