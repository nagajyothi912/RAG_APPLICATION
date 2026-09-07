#!/usr/bin/env python3
"""
Drive a week of support traffic through the shipped pipeline and let the app
trace it.

The Week 5 brief assumes a trace file grown from real use. This app has no real
users, so the traffic is simulated: 120 support tickets authored blind in
`eval/week5/ticket_bank.jsonl` (committed before any tracing code existed), plus
the 14 curated demo questions the chat UI offers, plus an optional 14-question
control. The questions are synthetic. The traces are not - every one is a real
run of `RagService.ask` against the real corpus with a real Groq key, and the
records are written by the app's own tracing, not by this script.

Three things this script does NOT do, on purpose:

- It does not reimplement the chat route. Filters are built exactly as
  `app/api/chat.py` builds them, `resolve_document` included, so a trace
  describes the production path rather than a lookalike.
- It does not choose which question runs under which configuration. Mode, top_k
  and filters come from a seeded, content-blind draw, so the author cannot have
  paired a hard question with a bad filter. Pairing them by hand would be
  authoring a failure mode.
- It does not drop a ticket that fails. A ticket that exhausts its retries is
  still traced, with its error, because a silently missing trace biases the
  random sample.

Usage:

    python scripts/simulate_support_traffic.py                    # the full run
    python scripts/simulate_support_traffic.py --dry-run --limit 5  # no Groq calls
    python scripts/simulate_support_traffic.py --resume           # after a rate limit
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

DEFAULT_OUT = ROOT / "docs" / "week5" / "traces.jsonl"
BANK = BACKEND / "eval" / "week5" / "ticket_bank.jsonl"
DEMO_SET = BACKEND / "eval" / "golden_set.json"

# Pin the documented configuration before app.config is imported. backend/.env
# is developer-local and overrides config.py; a stale one once published a whole
# section of results.md under the wrong threshold.
os.environ["CHUNK_STRATEGY"] = "heading"
os.environ["CHUNK_SIZE"] = "1000"
os.environ["CHUNK_OVERLAP"] = "100"
os.environ["TOP_K"] = "5"
os.environ["SCORE_THRESHOLD"] = "0.15"
# The committed 7-article corpus, keeping help_centre/ and policies/, so a
# trace's chunk ids carry the same prefixes results.md and the eval fixtures
# use. backend/data/docs is flat and gitignored, so a reviewer could not
# reproduce anything recorded against it.
os.environ["DOCS_DIR"] = str(ROOT / "sample_documents")
# Groq's own default temperature is why a live trace is not byte-replayable:
# the same prompt returns differently worded text on each call. Pinning it to 0
# is the precondition for the replay deliverable, and is what evaluate_week4.py
# already does for the same reason. The value is recorded in every trace.
os.environ["GROQ_TEMPERATURE"] = "0"
os.environ["TRACE_ENABLED"] = "true"

from app.config import settings  # noqa: E402
from app.services import rag_service as rs  # noqa: E402
from app.services import tracing  # noqa: E402

# The retrieval modes a user can pick, weighted the way the UI nudges them:
# week4 is the recommended badge, week3 is the toggle some people never moved.
MODE_WEIGHTS = [("week4", 78), ("week3", 22)]
TOP_K_WEIGHTS = [(5, 70), (3, 15), (8, 10), (10, 5)]
FILTER_WEIGHTS = [("none", 80), ("product_area", 12), ("source_file", 8)]


def weighted(rng: random.Random, pairs):
    values = [v for v, _ in pairs]
    weights = [w for _, w in pairs]
    return rng.choices(values, weights=weights, k=1)[0]


def load_bank() -> list[dict]:
    rows = []
    for line in BANK.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "_bank" in row:
            continue
        if row.get("retired"):
            continue
        rows.append(row)
    return rows


def load_demo() -> list[dict]:
    return json.loads(DEMO_SET.read_text(encoding="utf-8"))["questions"]


def build_filters(service, product_area: str | None, source_file: str | None) -> dict:
    """Exactly what app/api/chat.py does, including the 404-shaped None case."""
    filters: dict = {}
    if product_area:
        filters["product_area"] = product_area
    if source_file:
        resolved = service.resolve_document(source_file)
        if resolved is None:
            return {}
        filters["source"] = resolved
    return filters


def already_done(out: Path) -> set[str]:
    """source_ids whose trace exists and did not error."""
    if not out.exists():
        return set()
    done = set()
    for line in out.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("source_id") and rec.get("outcome", {}).get("status") != "error":
            done.add(rec["source_id"])
    return done


def install_retry(max_retries: int) -> None:
    """
    Retry Groq below the trace boundary, so a rate limit produces one trace per
    ticket rather than one per attempt.

    Patching the module attribute is the pattern this codebase already
    prescribes for its import-time constants. `capture` is threaded through
    untouched, so tracing still sees the prompt and the raw output.
    """
    original = rs.answer_with_groq
    retryable = {
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "APIStatusError",
        "APIError",
    }

    def retrying(client, model, question, results, gate_score=None, temperature=None, *, capture=None):
        for attempt in range(1, max_retries + 1):
            try:
                return original(
                    client, model, question, results,
                    gate_score=gate_score, temperature=temperature, capture=capture,
                )
            except Exception as exc:
                if attempt == max_retries or type(exc).__name__ not in retryable:
                    raise
                wait = min(2.0 * 2 ** (attempt - 1), 60.0)
                wait += random.uniform(0, 0.5 * wait)
                print(f"      retry {attempt}/{max_retries} in {wait:.1f}s ({type(exc).__name__})")
                time.sleep(wait)

    rs.answer_with_groq = retrying


def run_one(service, *, trace_id, pool, source_id, question, request, dry_run):
    filters = build_filters(service, request.get("product_area"), request.get("source_file"))
    if dry_run:
        results = service.retrieve(
            question, top_k=request["top_k"], filters=filters or None, mode=request["mode"]
        )
        return {"status": "dry-run", "n": len(results)}
    try:
        payload = service.ask(
            question,
            top_k=request["top_k"],
            filters=filters or None,
            mode=request["mode"],
            trace_extra={"pool": pool, "source_id": source_id, "trace_id": trace_id},
        )
        return {"status": "ok", "answer": payload["answer"][:70]}
    except Exception as exc:
        # The trace was still written by ask()'s finally block.
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--traffic-seed", type=int, default=20260907)
    ap.add_argument("--sleep", type=float, default=1.2, help="pacing between tickets, seconds")
    ap.add_argument("--max-retries", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--no-demo", action="store_true")
    ap.add_argument("--no-control", action="store_true", help="skip the unscoped demo control")
    ap.add_argument("--dry-run", action="store_true", help="retrieval only, zero Groq calls")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    os.environ["TRACE_PATH"] = str(args.out)
    settings.trace_path = args.out
    tracing.reset_trace_writer()

    if not args.dry_run and not settings.api_key:
        sys.exit("GROQ_API_KEY is not set. Generation traces need a real key.")

    install_retry(args.max_retries)

    print(f"Indexing {settings.resolved_docs_dir} ...")
    service = rs.RagService()
    print(f"  {len(service.store.chunks)} chunks, fingerprint {service.store.fingerprint}")

    rng = random.Random(args.traffic_seed)
    areas = service.store.product_areas()
    files = sorted({c.source for c in service.store.chunks})

    jobs: list[dict] = []

    # --- the random pool: the ticket bank, options drawn content-blind
    for i, ticket in enumerate(load_bank(), start=1):
        choice = weighted(rng, FILTER_WEIGHTS)
        product_area = weighted(rng, [(a, 1) for a in areas]) if choice == "product_area" else None
        source_file = weighted(rng, [(f, 1) for f in files]) if choice == "source_file" else None
        jobs.append(
            {
                "trace_id": f"TR-{i:04d}",
                "pool": "random",
                "source_id": ticket["ticket_id"],
                "question": ticket["question"],
                "request": {
                    "mode": weighted(rng, MODE_WEIGHTS),
                    "top_k": weighted(rng, TOP_K_WEIGHTS),
                    # The UI clears the product area whenever a document is
                    # picked, so a trace must never carry both.
                    "product_area": product_area,
                    "source_file": source_file,
                },
            }
        )

    # --- the demo pool: run the way it is actually demoed, or the bonus lies.
    # pickGolden scopes each question to its own document, and clears the scope
    # for the two contrast questions, whose whole point is the whole corpus.
    demo = load_demo()
    if not args.no_demo:
        for i, q in enumerate(demo, start=1):
            jobs.append(
                {
                    "trace_id": f"TD-{i:04d}",
                    "pool": "demo",
                    "source_id": q["id"],
                    "question": q["question"],
                    "request": {
                        "mode": "week4",
                        "top_k": 5,
                        "product_area": None,
                        "source_file": None if q.get("contrast") else q.get("source_file"),
                    },
                }
            )
    # --- the control: the same 14 questions with the scoping removed, so the
    # bonus can separate "the questions are easy" from "the UI narrows the
    # search for them". Excluded from every draw.
    if not args.no_demo and not args.no_control:
        for i, q in enumerate(demo, start=1):
            jobs.append(
                {
                    "trace_id": f"TU-{i:04d}",
                    "pool": "demo_unscoped",
                    "source_id": q["id"],
                    "question": q["question"],
                    "request": {"mode": "week4", "top_k": 5, "product_area": None, "source_file": None},
                }
            )

    if args.resume:
        done = already_done(args.out)
        before = len(jobs)
        jobs = [j for j in jobs if j["source_id"] not in done or j["pool"] == "demo_unscoped"]
        print(f"Resuming: {before - len(jobs)} already traced, {len(jobs)} to go")

    if args.limit:
        jobs = jobs[: args.limit]

    print(f"Running {len(jobs)} requests (sleep {args.sleep}s, dry_run={args.dry_run})\n")
    started = time.time()
    counts = {"ok": 0, "error": 0, "dry-run": 0}
    for n, job in enumerate(jobs, start=1):
        label = f"[{n:3d}/{len(jobs)}] {job['trace_id']} {job['source_id']:>5}"
        preview = job["question"][:58].replace("\n", " ")
        print(f"{label} {preview!r}")
        outcome = run_one(service, dry_run=args.dry_run, **job)
        counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
        if outcome["status"] == "error":
            print(f"      ERROR {outcome['error']}")
        if not args.dry_run and args.sleep:
            time.sleep(args.sleep)

    elapsed = time.time() - started
    print(f"\nDone in {elapsed/60:.1f} min: {counts}")
    if not args.dry_run:
        print(f"Traces: {args.out}")


if __name__ == "__main__":
    main()
