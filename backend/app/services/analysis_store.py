"""
Read side of the Week 5 error analysis.

Everything the Error Analysis tab shows is derived from artifacts that already
exist and are already the graded deliverables:

    docs/week5/traces.jsonl   the 148 traces the analysis was done on
    docs/week5/sample.json    the seeded draw of 20 + 10
    docs/week5/taxonomy.md    the ranked failure modes
    docs/week5/notes.md       the open coding, and the trace-to-mode table

Nothing here writes. The taxonomy and the open coding are parsed out of the
markdown rather than duplicated into a second source of truth, because a copy
would drift from the file the rubric is graded on and the UI would start
disagreeing with the write-up.

The trace file is ~1.4 MB, so it is parsed once and cached against the file's
mtime and size. That also means pointing TRACE_PATH at a live file and asking
again picks up new traces without a restart.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ROOT = BACKEND_ROOT.parent
WEEK5 = ROOT / "docs" / "week5"

TRACES = WEEK5 / "traces.jsonl"
SAMPLE = WEEK5 / "sample.json"
TAXONOMY = WEEK5 / "taxonomy.md"
NOTES = WEEK5 / "notes.md"

# `1. Refuses while ... | 3 | 15% | annoys the user | `TR-0055` |`
_TAXONOMY_ROW = re.compile(r"^\|\s*(\d+)\s*\|([^|]+)\|\s*(\d+)\s*\|\s*([\d.]+)%\s*\|([^|]+)\|([^|]+)\|")
_RESIDUAL_ROW = re.compile(r"^\|\s*—\s*\|([^|]+)\|\s*(\d+)\s*\|\s*([\d.]+)%")
_CODING_LINE = re.compile(r"^\d+\.\s+`(T[RD]-\d+)`\s+[-—]\s+(.+)$", re.M)

# The residual bucket in taxonomy.md: read, and found clean. Distinct from a
# trace that was never part of the sample and so has no verdict at all.
NO_DEFECT = "No defect seen"

_cache: dict[str, Any] = {}


def _stamp(path: Path) -> Optional[tuple]:
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _cached(key: str, path: Path, build):
    """Rebuild only when the file changed, so a live trace file stays live."""
    stamp = _stamp(path)
    hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    value = build()
    _cache[key] = (stamp, value)
    return value


def reset_cache() -> None:
    _cache.clear()


def trace_path(source: str = "analysis") -> Path:
    """
    'analysis' is the committed 148-trace run the write-up describes.
    'live' is whatever the running server is currently appending to.
    """
    return TRACES if source == "analysis" else Path(settings.resolved_trace_path)


def load_traces(source: str = "analysis") -> list[dict]:
    path = trace_path(source)

    def build() -> list[dict]:
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # A half-written final line is normal while a run is in flight.
                continue
        return out

    return _cached(f"traces:{path}", path, build)


def load_sample() -> dict:
    def build() -> dict:
        if not SAMPLE.exists():
            return {}
        return json.loads(SAMPLE.read_text(encoding="utf-8"))

    return _cached("sample", SAMPLE, build)


def load_taxonomy() -> dict:
    """The ranked modes, parsed out of taxonomy.md so the two cannot disagree."""

    def build() -> dict:
        if not TAXONOMY.exists():
            return {"modes": [], "residual": None, "sample_size": 0}
        modes, residual = [], None
        for line in TAXONOMY.read_text(encoding="utf-8").splitlines():
            row = _TAXONOMY_ROW.match(line.strip())
            if row:
                modes.append(
                    {
                        "rank": int(row.group(1)),
                        "name": row.group(2).strip(),
                        "count": int(row.group(3)),
                        "percent": float(row.group(4)),
                        "severity": row.group(5).strip(),
                        "example_trace_id": row.group(6).strip().strip("`"),
                    }
                )
                continue
            res = _RESIDUAL_ROW.match(line.strip())
            if res:
                residual = {
                    "name": res.group(1).strip(),
                    "count": int(res.group(2)),
                    "percent": float(res.group(3)),
                }
        total = sum(m["count"] for m in modes) + (residual["count"] if residual else 0)
        return {"modes": modes, "residual": residual, "sample_size": total}

    return _cached("taxonomy", TAXONOMY, build)


def load_open_coding() -> dict[str, str]:
    """trace_id -> the verbatim observation sentence written about it."""

    def build() -> dict[str, str]:
        if not NOTES.exists():
            return {}
        return {m.group(1): m.group(2).strip() for m in _CODING_LINE.finditer(NOTES.read_text("utf-8"))}

    return _cached("coding", NOTES, build)


def load_mode_map() -> dict[str, str]:
    """trace_id -> mode name, from the 'trace to mode' table in notes.md."""

    def build() -> dict[str, str]:
        if not NOTES.exists():
            return {}
        text = NOTES.read_text(encoding="utf-8")
        parts = text.split("### 4.1 Trace to mode")
        if len(parts) < 2:
            return {}
        block = parts[1].split("### 4.2")[0]
        out: dict[str, str] = {}
        for line in block.splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 2:
                continue
            label, ids = cells
            # "1. Refuses while ..." -> the mode name; "— no defect seen" is the
            # residual row and is normalised so the UI can style it apart from a
            # real mode rather than showing a stray em dash.
            name = re.sub(r"^\d+\.\s*", "", label).strip()
            name = re.sub(r"^[—-]\s*", "", name).strip()
            if name.lower().startswith("no defect"):
                name = NO_DEFECT
            for tid in re.findall(r"`(T[RD]-\d+)`", ids):
                out[tid] = name
        return out

    return _cached("modemap", NOTES, build)


def summarise(trace: dict) -> dict:
    """The compact row the trace list renders. Deliberately without prompts."""
    request = trace.get("request", {})
    retrieval = trace.get("retrieval", {})
    filters = request.get("filters") or {}
    chunks = retrieval.get("chunks", [])
    return {
        "trace_id": trace.get("trace_id", ""),
        "pool": trace.get("pool"),
        "source_id": trace.get("source_id"),
        "started_at": trace.get("started_at"),
        "question": request.get("question", ""),
        "mode": request.get("mode_effective", ""),
        "top_k": request.get("top_k_effective"),
        "filter": filters.get("source") or filters.get("product_area"),
        "status": trace.get("outcome", {}).get("status", ""),
        "answer_source": trace.get("answer", {}).get("source", ""),
        "refused": bool(retrieval.get("refused")),
        "gate_score": retrieval.get("gate_score"),
        "score_threshold": retrieval.get("score_threshold"),
        "generation_called": bool(trace.get("generation", {}).get("called")),
        "finish_reason": trace.get("generation", {}).get("finish_reason"),
        "chunks": len(chunks),
        "top_chunk": chunks[0]["chunk_uid"] if chunks else None,
        "answer_preview": (trace.get("answer", {}).get("text") or "")[:180],
        "latency_ms": (trace.get("latency_ms") or {}).get("total"),
    }


def annotate(row: dict) -> dict:
    """Attach the analysis a human wrote about this trace, when there is one."""
    sample = load_sample()
    tid = row["trace_id"]
    row["sampled"] = (
        "random" if tid in set(sample.get("random", []))
        else "demo" if tid in set(sample.get("demo", []))
        else None
    )
    row["open_coding"] = load_open_coding().get(tid)
    row["failure_mode"] = load_mode_map().get(tid)
    return row
