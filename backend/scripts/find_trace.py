#!/usr/bin/env python3
"""
Find a past answer from the trace log - the support drill's tool.

    # "a wrong answer about refunds yesterday afternoon"
    python scripts/find_trace.py --text refund --day yesterday --hours 12-18

    # the other slices
    python scripts/find_trace.py --user user --prompt-version v1
    python scripts/find_trace.py --input-type follow_up --status answered
    python scripts/find_trace.py --outliers            # cost above the p95
    python scripts/find_trace.py --context refund_policy.txt#0

    # one trace in full (per-span latency, tokens, cost, prompt version, context ids)
    python scripts/find_trace.py --show <trace_id>  > trace.json

Searches the SQLite index beside the log (built on first use, refreshed whenever
the JSONL has grown, so a stale index can never hide the newest answers). The
question AND the answer are both searchable: a complaint describes the output.
Prints how long the search took, because the drill is timed.

`--log` points at another log (the drill uses backend/data/traces/drill/).
Times are shown and filtered in UTC; `--day`/`--hours` are read as UTC too, with
`--tz-offset 5.5` to give them in local time (IST).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.trace_index import index_for  # noqa: E402

DEFAULT_LOG = BACKEND / "data" / "traces" / "chat_traces.jsonl"


def window(day: str | None, hours: str | None, tz_offset: float) -> tuple[str | None, str | None]:
    """'yesterday' + '12-18' (local) -> UTC ISO bounds usable against started_at."""
    if not day and not hours:
        return None, None
    tz = timezone(timedelta(hours=tz_offset))
    today = datetime.now(tz).date()
    d = today - timedelta(days=1) if day in (None, "yesterday") else (
        today if day == "today" else datetime.strptime(day, "%Y-%m-%d").date())
    h0, h1 = (0, 24)
    if hours:
        a, b = hours.split("-")
        h0, h1 = int(a), int(b)
    start = datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(hours=h0)
    end = datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(hours=h1)
    fmt = lambda x: x.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")  # noqa: E731
    return fmt(start), fmt(end)


def ensure_index(log: Path):
    """
    Return an index guaranteed to match the log. Stale if the row count differs OR
    the log was written after the index (same count, different content: a re-seeded
    or edited log). The live app writes the index right after the JSONL, so a gap
    of more than a second only happens when something else touched the log.
    """
    idx = index_for(log)
    if not log.exists():
        return idx
    lines = sum(1 for _ in open(log, encoding="utf-8"))
    stale = (
        not idx.path.exists()
        or idx.count() != lines
        or log.stat().st_mtime > idx.path.stat().st_mtime + 1.0
    )
    if stale:
        idx.rebuild(log)
    return idx


def clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--text", help="words in the question or the answer")
    ap.add_argument("--since"), ap.add_argument("--until")
    ap.add_argument("--day", help="yesterday | today | YYYY-MM-DD")
    ap.add_argument("--hours", help="e.g. 12-18 (with --day, default yesterday)")
    ap.add_argument("--tz-offset", type=float, default=0.0, help="hours from UTC for --day/--hours")
    ap.add_argument("--user"), ap.add_argument("--prompt-version"), ap.add_argument("--input-type")
    ap.add_argument("--status"), ap.add_argument("--context", help="substring of a retrieved chunk id")
    ap.add_argument("--min-cost", type=float)
    ap.add_argument("--outliers", action="store_true", help="cost at or above the p95")
    ap.add_argument("--slowest", action="store_true")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--show", metavar="TRACE_ID", help="print one full trace as JSON")
    args = ap.parse_args()

    t0 = time.perf_counter()
    if not args.log.exists():
        print(f"no trace log at {args.log}", file=sys.stderr)
        return 2

    if args.show:
        for line in open(args.log, encoding="utf-8"):
            if args.show in line[:200]:
                rec = json.loads(line)
                if rec.get("trace_id", "").startswith(args.show):
                    print(json.dumps(rec, indent=2, ensure_ascii=False))
                    return 0
        print(f"trace {args.show} not found", file=sys.stderr)
        return 1

    idx = ensure_index(args.log)
    since, until = window(args.day, args.hours, args.tz_offset)
    since, until = args.since or since, args.until or until
    min_cost = args.min_cost
    order = "started_at DESC"
    if args.outliers:
        min_cost = idx.cost_percentile(0.95)
        order = "cost_usd DESC"
    if args.slowest:
        order = "total_ms DESC"
    rows = idx.search(text=args.text, since=since, until=until, user=args.user,
                      prompt_version=args.prompt_version, input_type=args.input_type,
                      status=args.status, min_cost=min_cost, context=args.context,
                      order=order, limit=args.limit)
    elapsed = time.perf_counter() - t0

    for r in rows:
        print(f"{r['started_at']}  {r['trace_id'][:12]}  user={r['user']:<8} {r['prompt_version']}  "
              f"{r['input_type']:<9} {r['status']:<8} ${r['cost_usd'] or 0:.6f} {r['total_ms'] or 0:>7.0f}ms")
        print(f"    Q: {clip(r['question'], 110)}")
        print(f"    A: {clip(r['answer'], 150)}")
        print(f"    ctx: {r['context_ids']}")
    print(f"\n{len(rows)} match(es) of {idx.count()} indexed traces in {elapsed * 1000:.0f} ms "
          f"(slice: {', '.join(k for k, v in vars(args).items() if v and k in ('text','since','until','day','hours','user','prompt_version','input_type','status','context','min_cost','outliers','slowest')) or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
