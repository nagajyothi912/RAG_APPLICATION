"""
Second sink for the Week 5 trace record: Langfuse.

`tracing.py` stays the record of truth. The committed error analysis is pinned to
`docs/week5/traces.jsonl` by sha256, the sampler draws from it, the replay script
reads it, and 42 tests assert against it - so the JSONL is not going anywhere and
Langfuse does not replace it. What Langfuse adds is a place to *read* traces:
filtering, latency and cost rollups, and a UI that beats scrolling a 1.4 MB file.

The important property of this module is that it consumes the **same record dict**
`tracing.build_chat_record` already produces. One shape, two sinks. That is what
makes the backfill script trustworthy: replaying the committed JSONL into Langfuse
produces exactly the structure a live request would have produced, rather than a
second, subtly different serialisation that drifts from the first.

Each record becomes one trace with two child observations:

    chat  (span)                input: question              output: answer shown
    |- retrieval (retriever)    input: query + filters       output: ranked chunk ids
    |- generation (generation)  input: rendered messages     output: raw model text

Trace ids come from the record's own `trace_id` via
`Langfuse.create_trace_id(seed=...)`, which is deterministic. Re-running the
backfill therefore updates the same traces instead of duplicating them, and
`TR-0037` in the write-up resolves to one stable URL.

Off unless `LANGFUSE_ENABLED` is set and both keys are present. Emission failures
are swallowed: a telemetry sink must never take a user's answer down with it, and
the JSONL has already been written by the time this runs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_client: Any = None
_checked = False
_broken = False


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _shift(start: Optional[datetime], ms: Optional[float]) -> Optional[datetime]:
    if start is None or ms is None:
        return None
    return start + timedelta(milliseconds=float(ms))


def get_client() -> Any:
    """
    Lazy singleton, mirroring get_reranker() and get_trace_writer().

    The langfuse import is deferred to first use so the dependency stays
    optional: a checkout without it installed, or with the feature off, imports
    this module and pays nothing.
    """
    global _client, _checked
    if _checked:
        return _client
    _checked = True
    if not settings.langfuse_enabled:
        return None
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning("LANGFUSE_ENABLED is set but the keys are not; Langfuse tracing is off")
        return None
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            environment=settings.langfuse_environment,
        )
    except Exception as exc:  # noqa: BLE001 - never fail a request over telemetry
        logger.warning("Langfuse client unavailable (%s); continuing without it", exc)
        _client = None
    return _client


def reset_client() -> None:
    global _client, _checked, _broken
    _client, _checked, _broken = None, False, False


def enabled() -> bool:
    return get_client() is not None


def trace_url(local_trace_id: str) -> Optional[str]:
    client = get_client()
    if client is None:
        return None
    try:
        return f"{settings.langfuse_base_url.rstrip('/')}/trace/{client.create_trace_id(seed=local_trace_id)}"
    except Exception:  # noqa: BLE001
        return None


def emit(record: dict, *, extra_tags: Optional[list[str]] = None) -> Optional[str]:
    """
    Push one trace record to Langfuse. Returns the Langfuse trace id, or None.

    Never raises. After the first failure the sink goes quiet rather than logging
    once per request for the life of the process.
    """
    global _broken
    client = get_client()
    if client is None or _broken:
        return None
    try:
        return _emit(client, record, extra_tags or [])
    except Exception as exc:  # noqa: BLE001
        _broken = True
        logger.warning("Langfuse emit failed (%s); disabling it for this process", exc)
        return None


def _clean_params(params: Optional[dict]) -> Optional[dict]:
    if not params:
        return None
    cleaned = {k: v for k, v in params.items() if v is not None}
    return cleaned or None


def _emit(client: Any, record: dict, extra_tags: list[str]) -> str:
    from langfuse import propagate_attributes

    local_id = record["trace_id"]
    trace_id = client.create_trace_id(seed=local_id)

    request = record["request"]
    retrieval = record["retrieval"]
    generation = record["generation"]
    outcome = record["outcome"]
    config = record.get("config", {})
    latency = record.get("latency_ms", {})

    start = _parse_ts(record.get("started_at"))
    end = _parse_ts(record.get("finished_at"))

    # `retrieval:`, not `mode:`. The Week 5 backfill tags traces with the failure
    # mode assigned in taxonomy.md as `mode:1` ... `mode:5`, and those are a
    # different axis entirely from which retriever ran. Sharing the prefix put
    # "week4" in the same filter list as "3", which reads as a sixth failure mode.
    tags = [
        f"retrieval:{request['mode_effective']}",
        f"status:{outcome['status']}",
        f"answer:{record['answer']['source']}",
    ]
    if record.get("pool"):
        tags.append(f"pool:{record['pool']}")
    if retrieval.get("refused"):
        tags.append("refused")
    tags += extra_tags

    attrs = propagate_attributes(
        trace_name=f"chat: {request['question'][:60]}",
        tags=tags,
        session_id=record.get("pool"),
        metadata={"local_trace_id": local_id, "schema_version": record.get("schema_version")},
    )
    attrs.__enter__()
    root = client.start_observation(
        trace_context={"trace_id": trace_id},
        name="chat",
        as_type="span",
        input=request["question"],
        output=record["answer"]["text"],
        metadata={
            "local_trace_id": local_id,
            "pool": record.get("pool"),
            "source_id": record.get("source_id"),
            "outcome": outcome,
            "filters": request["filters"],
            "top_k": request["top_k_effective"],
            "corpus_fingerprint": config.get("corpus", {}).get("fingerprint"),
            "chunking": f"{config.get('chunk_strategy')}/{config.get('chunk_size')}/{config.get('chunk_overlap')}",
            "embed_model": config.get("embed_model"),
            "latency_ms": latency,
        },
    )
    # Trace-level input and output, so the list view shows the question and the
    # answer without opening the trace. In the v4 SDK the trace name and tags
    # come from propagate_attributes (applied by the caller in _emit), and the
    # trace body from set_trace_io on the root span.
    root.set_trace_io(input=request["question"], output=record["answer"]["text"])

    # --- retrieval
    chunks = retrieval.get("chunks", [])
    retrieval_span = root.start_observation(
        name="retrieval",
        as_type="retriever",
        input={
            "query": request["question"],
            "mode": request["mode_effective"],
            "top_k": request["top_k_effective"],
            "filters": request["filters"],
        },
        output=[
            {
                "rank": c["rank"],
                "chunk_uid": c["chunk_uid"],
                "article_id": c["article_id"],
                "section": c["section"],
                "dense_score": c["dense_score"],
                "rerank_score": c["rerank_score"],
                "retriever": c["retriever"],
            }
            for c in chunks
        ],
        metadata={
            "hybrid": retrieval.get("hybrid"),
            "reranked": retrieval.get("reranked"),
            "gate_score": retrieval.get("gate_score"),
            "score_threshold": retrieval.get("score_threshold"),
            "refused": retrieval.get("refused"),
            "chunks_returned": len(chunks),
        },
    )
    retrieval_span.end()

    # --- generation. When the model was never called, an event is recorded
    # instead of an empty generation: "no Groq call was made" is the single most
    # important thing a refusal trace can say, and a missing span reads as
    # missing data rather than as a decision the gate took.
    if generation.get("called"):
        usage = generation.get("usage") or {}
        usage_details = {
            k: v
            for k, v in {
                "input": usage.get("prompt_tokens"),
                "output": usage.get("completion_tokens"),
                "total": usage.get("total_tokens"),
            }.items()
            if isinstance(v, int)
        }
        gen = root.start_observation(
            name="generation",
            as_type="generation",
            input=[
                {"role": "system", "content": generation.get("system_prompt")},
                {"role": "user", "content": generation.get("user_prompt")},
            ],
            output=generation.get("raw_output"),
            model=generation.get("model"),
            model_parameters=_clean_params(generation.get("params")),
            usage_details=usage_details or None,
            metadata={
                "prompt_id": generation.get("prompt_id"),
                "finish_reason": generation.get("finish_reason"),
                "refusal": generation.get("refusal"),
                "context_chars": generation.get("context_chars"),
                "answer_source": record["answer"]["source"],
            },
            level="WARNING" if generation.get("refusal") == "empty_content" else None,
        )
        gen.end()
    else:
        root.create_event(
            name="refused-before-generation",
            input=request["question"],
            output=record["answer"]["text"],
            metadata={
                "gate_score": retrieval.get("gate_score"),
                "score_threshold": retrieval.get("score_threshold"),
                "reason": "best dense cosine below SCORE_THRESHOLD; no Groq call was made",
            },
            level="WARNING",
        )

    if outcome["status"] == "error":
        root.update(level="ERROR", status_message=outcome.get("error_message"))

    root.end()
    attrs.__exit__(None, None, None)
    return trace_id


def flush() -> None:
    client = get_client()
    if client is not None:
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            pass
