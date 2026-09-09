"""
Read-only routes behind the Error Analysis tab.

These serve the Week 5 artifacts that are already committed: the 148 traces the
analysis was done on, the seeded sample, the ranked taxonomy, and the open
coding. Nothing here writes, and nothing here recomputes the analysis - the
taxonomy is parsed out of taxonomy.md rather than being duplicated in code, so
the UI cannot start disagreeing with the file the rubric is graded on.

`source=live` points the same endpoints at whatever TRACE_PATH the running
server is appending to, so a new failure can be inspected while it is still
warm. `source=analysis` is the default and is the committed run.
"""

from fastapi import APIRouter, HTTPException, Query

from app.schemas import AnalysisSummary, TraceDetail, TraceListResponse, TraceRow
from app.services import analysis_store as store

router = APIRouter(tags=["analysis"], prefix="/analysis")

SOURCES = ("analysis", "live")


def _traces(source: str) -> list[dict]:
    if source not in SOURCES:
        raise HTTPException(status_code=400, detail=f"source must be one of {SOURCES}")
    return store.load_traces(source)


@router.get("/summary", response_model=AnalysisSummary)
def summary(source: str = Query("analysis")) -> AnalysisSummary:
    traces = _traces(source)
    taxonomy = store.load_taxonomy()
    sample = store.load_sample()

    pools: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for trace in traces:
        pools[trace.get("pool") or "live"] = pools.get(trace.get("pool") or "live", 0) + 1
        status = trace.get("outcome", {}).get("status", "unknown")
        statuses[status] = statuses.get(status, 0) + 1

    first = traces[0] if traces else {}
    return AnalysisSummary(
        available=bool(traces),
        source=source,
        traces=len(traces),
        pools=pools,
        statuses=statuses,
        modes=taxonomy["modes"],
        residual=taxonomy["residual"],
        sample_size=taxonomy["sample_size"],
        sample_seed=sample.get("seed"),
        sampled_random=sample.get("random", []),
        sampled_demo=sample.get("demo", []),
        traces_sha256=sample.get("traces_sha256", ""),
        corpus_fingerprint=first.get("config", {}).get("corpus", {}).get("fingerprint", ""),
        prompt_id=first.get("generation", {}).get("prompt_id") or "",
        coded=len(store.load_open_coding()),
    )


@router.get("/traces", response_model=TraceListResponse)
def list_traces(
    source: str = Query("analysis"),
    q: str | None = Query(None, description="substring of the question or the answer"),
    pool: str | None = None,
    mode: str | None = Query(None, description="week3 | week4"),
    status: str | None = Query(None, description="answered | refused | error"),
    sampled: str | None = Query(None, description="random | demo | any"),
    failure_mode: str | None = Query(None, description="exact mode name, or 'any'"),
    refused: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> TraceListResponse:
    rows = [store.annotate(store.summarise(t)) for t in _traces(source)]

    if q:
        needle = q.strip().lower()
        rows = [
            r for r in rows
            if needle in r["question"].lower() or needle in (r["answer_preview"] or "").lower()
        ]
    if pool:
        rows = [r for r in rows if r["pool"] == pool]
    if mode:
        rows = [r for r in rows if r["mode"] == mode]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if refused is not None:
        rows = [r for r in rows if r["refused"] is refused]
    if sampled:
        rows = [r for r in rows if r["sampled"] is not None] if sampled == "any" \
            else [r for r in rows if r["sampled"] == sampled]
    if failure_mode:
        rows = [r for r in rows if r["failure_mode"]] if failure_mode == "any" \
            else [r for r in rows if r["failure_mode"] == failure_mode]

    total = len(rows)
    window = rows[offset : offset + limit]
    return TraceListResponse(
        total=total, offset=offset, limit=limit, rows=[TraceRow(**r) for r in window]
    )


@router.get("/traces/{trace_id}", response_model=TraceDetail)
def get_trace(trace_id: str, source: str = Query("analysis")) -> TraceDetail:
    for trace in _traces(source):
        if trace.get("trace_id") == trace_id:
            return TraceDetail(
                trace=trace,
                sampled=store.annotate(store.summarise(trace))["sampled"],
                open_coding=store.load_open_coding().get(trace_id),
                failure_mode=store.load_mode_map().get(trace_id),
            )
    raise HTTPException(status_code=404, detail=f"No trace {trace_id!r} in the {source} trace file.")
