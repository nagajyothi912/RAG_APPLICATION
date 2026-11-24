#!/usr/bin/env python3
"""
Cost per request, split by stage, from a trace log.

    python scripts/cost_report.py [--log FILE] [--trace TRACE_ID]

For a whole log: requests, total cost, cost per request (mean, p50, p95), and the
mean cost / time / tokens of each stage (rewrite, retrieval, generation, tools).
For one trace (--trace): that single request's stage split, which is the table
`docs/week11/cost_by_stage.md` quotes for the drilled request.

`tools` is 0 on /api/chat because the RAG chat calls no tools; it is in the table
so the same report reads correctly for the tool-calling assistant once it logs.
Cost is tokens x the price table in app/services/pricing.py - it is computed, not
billed, so check it against the Groq usage page before quoting it as money.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

STAGES = ("rewrite", "retrieval", "generation", "tools", "other")


def load(path: Path) -> list[dict]:
    out = []
    for line in open(path, encoding="utf-8"):
        if line.strip():
            rec = json.loads(line)
            if rec.get("event") == "chat" and "cost_usd" in rec:
                out.append(rec)
    return out


def pct(vals: list[float], q: float) -> float:
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(q * len(vals)))] if vals else 0.0


def stage_split(rec: dict) -> dict:
    spans = {s["name"]: s for s in rec.get("spans", [])}
    out = {}
    for st in STAGES:
        s = spans.get(st)
        out[st] = {
            "ms": s["latency_ms"] if s else 0.0,
            "tokens": ((s or {}).get("tokens_in") or 0) + ((s or {}).get("tokens_out") or 0),
            "usd": rec["cost_usd"].get(st, 0.0),
        }
    return out


def summarise(records: list[dict]) -> dict:
    costs = [r["cost_usd"]["total"] for r in records]
    per_stage = {st: [stage_split(r)[st] for r in records] for st in STAGES}
    return {
        "requests": len(records),
        "cache_hits": sum(1 for r in records if (r.get("cache") or {}).get("hit")),
        "total_usd": sum(costs),
        "mean_usd": statistics.mean(costs) if costs else 0.0,
        "p50_usd": pct(costs, 0.5), "p95_usd": pct(costs, 0.95),
        "tokens_mean": statistics.mean(r["tokens"]["total"] for r in records) if records else 0,
        "latency_p50_ms": pct([r["latency_ms"]["total"] for r in records], 0.5),
        "latency_p95_ms": pct([r["latency_ms"]["total"] for r in records], 0.95),
        "stages": {
            st: {
                "mean_usd": statistics.mean(x["usd"] for x in v) if v else 0.0,
                "mean_ms": statistics.mean(x["ms"] for x in v) if v else 0.0,
                "mean_tokens": statistics.mean(x["tokens"] for x in v) if v else 0.0,
            } for st, v in per_stage.items()
        },
    }


def render(summary: dict, title: str) -> str:
    s = summary
    lines = [f"### {title}", "",
             f"{s['requests']} requests ({s['cache_hits']} cache hits). "
             f"Cost per request: mean ${s['mean_usd']:.6f}, p50 ${s['p50_usd']:.6f}, p95 ${s['p95_usd']:.6f}. "
             f"Total ${s['total_usd']:.6f}. Mean {s['tokens_mean']:.0f} tokens/request. "
             f"Latency p50 {s['latency_p50_ms']:.0f} ms, p95 {s['latency_p95_ms']:.0f} ms.", "",
             "| stage | mean cost / request | share of cost | mean time | mean tokens |", "|---|---|---|---|---|"]
    tot = s["mean_usd"] or 1.0
    for st in STAGES:
        d = s["stages"][st]
        lines.append(f"| {st} | ${d['mean_usd']:.6f} | {100 * d['mean_usd'] / tot:.0f}% | {d['mean_ms']:.0f} ms | {d['mean_tokens']:.0f} |")
    return "\n".join(lines)


def render_one(rec: dict) -> str:
    sp = stage_split(rec)
    lines = [f"trace {rec['trace_id']}  prompt {rec['generation']['prompt_version']}  total ${rec['cost_usd']['total']:.6f}", "",
             "| stage | cost | share | time | tokens |", "|---|---|---|---|---|"]
    tot = rec["cost_usd"]["total"] or 1.0
    for st in STAGES:
        d = sp[st]
        lines.append(f"| {st} | ${d['usd']:.6f} | {100 * d['usd'] / tot:.0f}% | {d['ms']:.0f} ms | {d['tokens']} |")
    lines.append(f"| **total** | **${rec['cost_usd']['total']:.6f}** | | {rec['latency_ms']['total']:.0f} ms | {rec['tokens']['total']} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=Path, default=BACKEND / "data" / "traces" / "chat_traces.jsonl")
    ap.add_argument("--trace")
    a = ap.parse_args()
    recs = load(a.log)
    if a.trace:
        rec = next((r for r in recs if r["trace_id"].startswith(a.trace)), None)
        if rec is None:
            print("trace not found", file=sys.stderr)
            return 1
        print(render_one(rec))
    else:
        print(render(summarise(recs), str(a.log)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
