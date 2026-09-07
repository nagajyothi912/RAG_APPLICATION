"""
Per-request trace log for the Week 5 error analysis.

Nothing in this app persisted a request before Week 5. `logging.basicConfig`
wrote a couple of lines to stderr and that was the whole record, which is fine
for watching a server and useless for reading twenty answers a week later.

A trace here is a complete record of one `RagService.ask` call: the question,
the configuration the index was built under, every retrieved chunk with each
stage's score, the fully rendered prompt, the model and its parameters, the raw
model output, and the answer the user actually saw. That list is the Week 5
brief's own definition of a replayable trace, and each field is here because
replay needs it:

- The **rendered prompt** is stored verbatim rather than reconstructed. The user
  prompt is `format_citation(chunk)` interleaved with chunk text, so rebuilding
  it means re-implementing that function, and any later edit to it would
  silently invalidate every trace already on disk. Chunk text is deliberately
  *not* stored a second time alongside it - it is already inside the prompt.
- The **raw model output** is kept even when the user saw something else.
  `answer_with_groq` has three exits and two of them replace the model's words:
  the pre-LLM gate (no call was made at all) and the empty-content fallback (a
  call was made and came back blank). Those need opposite fixes and are
  indistinguishable from the answer text alone, so `answer.source` names which
  one fired.
- The **corpus fingerprint** and per-chunk `text_sha256` exist because chunk ids
  are positional and only valid at one chunking configuration, and because
  `backend/data/docs/**` is gitignored. Without them, replaying a trace against
  a corpus that has moved produces a plausible-looking but meaningless diff.

Writing is off by default (`TRACE_ENABLED`). The test suite and both evaluation
scripts must be able to run without producing a byte of trace output, and the
evaluation scripts additionally bypass `ask` entirely - tracing `evaluate_week4`
would dump four near-duplicate ablation records per question into the file the
error analysis reads from.

This module is a leaf: it imports `app.config` and the standard library only, so
`rag_service` gains no import cycle and the evaluation scripts do not drag trace
configuration in behind them.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from app.config import settings

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"

# Three consecutive write failures and the writer gives up for the life of the
# process. A read-only mount would otherwise emit one warning per request.
_MAX_CONSECUTIVE_FAILURES = 3


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_sha(text: str, n: int = 12) -> str:
    return sha256_hex(text)[:n]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def corpus_fingerprint(chunks: Iterable[Any]) -> str:
    """
    One short hash identifying exactly which chunks are in the index.

    Answers "am I replaying against the same corpus?" in a single comparison.
    Cheap enough to compute on every reindex - the shipped corpus is 30 chunks.
    """
    lines = sorted(
        f"{getattr(c, 'source', '')}#{getattr(c, 'chunk_id', '')}:{sha256_hex(getattr(c, 'text', ''))}"
        for c in chunks
    )
    return sha256_hex("\n".join(lines))[:16]


class TraceWriter:
    """Append-only JSONL writer. `write` never raises."""

    def __init__(self, path: Path | str, enabled: bool = False, include_prompts: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.include_prompts = include_prompts
        self._lock = threading.Lock()
        self._failures = 0
        self._broken = False

    def write(self, record: dict) -> None:
        if not self.enabled or self._broken:
            return
        try:
            # Serialise outside the lock, write inside it. `default=str` is a
            # last resort so an unexpected object can never fail a request; the
            # numbers are coerced explicitly in `build_chat_record` instead,
            # because a stringified float would quietly break replay comparison.
            line = json.dumps(record, ensure_ascii=False, default=str)
            with self._lock:
                # Reopen per write rather than holding a handle: the file can
                # then be rotated or moved between requests without leaving the
                # process writing to an unlinked inode. The lock is what makes
                # "one valid JSON object per line" true - the chat route is a
                # sync def, so Starlette runs it in a threadpool and two 8 KB
                # lines would otherwise interleave into unparseable records.
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            self._failures = 0
        except Exception as exc:  # noqa: BLE001 - a trace must never fail a request
            self._failures += 1
            if self._failures >= _MAX_CONSECUTIVE_FAILURES:
                self._broken = True
                logger.warning("Trace writing disabled after %s failures: %s", self._failures, exc)
            else:
                logger.warning("Trace write failed (%s): %s", self._failures, exc)


_writer: Optional[TraceWriter] = None


def get_trace_writer() -> TraceWriter:
    """
    Lazy singleton, mirroring `get_reranker()` and `get_rag_service()`.

    Deliberately *not* a module constant snapshotted at import: `rag_service`
    does that for SCORE_THRESHOLD and it is a documented gotcha, since
    monkeypatching settings afterwards has no effect. Tracing has to be
    switchable from a test, so the settings are read on first use and the
    singleton is resettable.
    """
    global _writer
    if _writer is None:
        _writer = TraceWriter(
            path=settings.resolved_trace_path,
            enabled=settings.trace_enabled,
            include_prompts=settings.trace_include_prompts,
        )
    return _writer


def reset_trace_writer() -> None:
    """Drop the singleton so a test or a script can rebuild it."""
    global _writer
    _writer = None


def _f(value: Any, digits: int = 6) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_chat_record(
    *,
    trace_id: str,
    started_at: str,
    finished_at: str,
    question: str,
    mode_requested: Optional[str],
    mode_effective: str,
    top_k_requested: Optional[int],
    top_k_effective: int,
    filters: Optional[dict],
    config: dict,
    results: Iterable[Any],
    gate_score: float,
    score_threshold: float,
    hybrid: bool,
    reranked: bool,
    answer_text: str,
    answer_source: str,
    capture: Optional[dict],
    error: Optional[BaseException],
    latency_ms: dict,
    include_prompts: bool = True,
    pool: Optional[str] = None,
    source_id: Optional[str] = None,
) -> dict:
    """
    Build one trace record. The whole schema lives here, so the replay script
    and the tests have exactly one file to read. Chunks are duck-typed.
    """
    capture = capture or {}

    chunks = []
    for rank, (chunk, scored) in enumerate(results or [], start=1):
        text = getattr(chunk, "text", "") or ""
        chunks.append(
            {
                "rank": rank,
                # `source#chunk_id` is the identity, not the store index:
                # week3 builds Scored(index=-1), so the index is meaningless
                # for half of every run.
                "chunk_uid": f"{getattr(chunk, 'source', '')}#{getattr(chunk, 'chunk_id', '')}",
                "source": getattr(chunk, "source", ""),
                "chunk_id": _i(getattr(chunk, "chunk_id", None)),
                "store_index": _i(getattr(scored, "index", None)),
                "article_id": getattr(chunk, "article_id", ""),
                "product_area": getattr(chunk, "product_area", ""),
                "last_updated": getattr(chunk, "last_updated", ""),
                "section": getattr(chunk, "section", ""),
                "dense_score": _f(getattr(scored, "dense_score", 0.0), 4),
                "keyword_score": _f(getattr(scored, "keyword_score", 0.0), 4),
                "fused_score": _f(getattr(scored, "fused_score", 0.0), 6),
                "rerank_score": _f(getattr(scored, "rerank_score", None), 4),
                "dense_rank": _i(getattr(scored, "dense_rank", None)),
                "keyword_rank": _i(getattr(scored, "keyword_rank", None)),
                "retriever": getattr(scored, "retriever", "dense"),
                "text_sha256": sha256_hex(text),
                "text_chars": len(text),
                "preview": text.strip()[:180],
            }
        )

    generation = {
        "called": bool(capture.get("called", False)),
        "prompt_id": capture.get("prompt_id"),
        "prompt_version": capture.get("prompt_version"),
        "prompt_sha256": capture.get("prompt_sha256"),
        "system_prompt": capture.get("system_prompt") if include_prompts else None,
        "user_prompt": capture.get("user_prompt") if include_prompts else None,
        "user_prompt_sha256": capture.get("user_prompt_sha256"),
        "context_chars": _i(capture.get("context_chars")),
        "provider": "groq",
        "base_url": config.get("groq_base_url"),
        "model": capture.get("model"),
        "params": capture.get("params"),
        "raw_output": capture.get("raw_output"),
        "finish_reason": capture.get("finish_reason"),
        "usage": capture.get("usage"),
        "refusal": capture.get("refusal"),
        "api_latency_ms": _f(capture.get("api_latency_ms"), 2),
    }

    if error is not None:
        status = "error"
    elif gate_score < score_threshold:
        status = "refused"
    else:
        status = "answered"

    record = {
        "schema_version": SCHEMA_VERSION,
        "trace_id": trace_id,
        "event": "chat",
        "started_at": started_at,
        "finished_at": finished_at,
        "outcome": {
            "status": status,
            "error_type": None if error is None else type(error).__name__,
            "error_message": None if error is None else str(error),
        },
        "request": {
            "question": question,
            "question_sha256": sha256_hex(question),
            "mode_requested": mode_requested,
            "mode_effective": mode_effective,
            "top_k_requested": _i(top_k_requested),
            "top_k_effective": _i(top_k_effective),
            "filters": filters or {},
        },
        "config": config,
        "retrieval": {
            "mode": mode_effective,
            "top_k": _i(top_k_effective),
            "hybrid": bool(hybrid),
            "reranked": bool(reranked),
            "gate_score": _f(gate_score, 4),
            "score_threshold": _f(score_threshold, 4),
            "refused": bool(gate_score < score_threshold),
            "chunks": chunks,
        },
        "generation": generation,
        "answer": {
            "text": answer_text,
            "source": answer_source,
            "chars": len(answer_text or ""),
        },
        "latency_ms": {k: _f(v, 2) for k, v in (latency_ms or {}).items()},
    }
    # Set only by the traffic simulator, so the sampler can tell the random
    # pool from the curated demo pool. A live request has neither.
    if pool is not None:
        record["pool"] = pool
    if source_id is not None:
        record["source_id"] = source_id
    return record
