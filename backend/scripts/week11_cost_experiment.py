#!/usr/bin/env python3
"""
Measured cost-per-request experiment: exact-match answer cache OFF vs ON.

Replays the same N-request sequence twice through the live pipeline (Groq, the
production temperature setting) and reads cost from the traces the app itself
wrote, split by stage. The only variable is CACHE_ENABLED.

Two sequences: `organic` (the Week 5 'random' pool, in order: no question repeats)
and `faq` (8 FAQ questions x4 plus 8 organic singles: a 60% repeat rate, an assumption).
Output: data/traces/cost_experiment/<kind>_cache_{off,on}.jsonl and <kind>_summary.json used by docs/week11/cost_by_stage.md.

    python scripts/week11_cost_experiment.py --kind faq|organic [--n 30]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

OUT = BACKEND / "data" / "traces" / "cost_experiment"


FAQ = [  # the questions a support desk gets over and over (the suite's guard cases)
    "How many days do I have to ask for a refund?",
    "Where will my refund be credited and when?",
    "Can I get a refund for the OTT add-on I redeemed last week?",
    "What is the installation charge for the AirFiber_599_1M plan?",
    "my payment didn't go through, will my internet stop immediately?",
    "What OTT apps are included with AirFiber_1199_1M?",
    "does the 30 day money back guarantee apply to me",
    "How do I raise a refund request?",
]


def organic(n: int) -> list[str]:
    """First n 'random'-pool questions of the Week 5 traffic, in order: 0 repeated questions."""
    path = BACKEND.parent / "docs" / "week5" / "traces.jsonl"
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return [r["request"]["question"] for r in rows if r.get("pool") == "random"][:n]


def faq_shaped(seed: int = 7) -> list[str]:
    """8 FAQ questions x4 + 8 organic singles = 40 requests, 16 distinct: a 60% repeat rate.
    The rate is an ASSUMPTION about support traffic, chosen to show the mechanism - it is
    not measured from this app's users."""
    import random
    seq = FAQ * 4 + organic(8)
    random.Random(seed).shuffle(seq)
    return seq


def questions(kind: str, n: int) -> list[str]:
    return organic(n) if kind == "organic" else faq_shaped()


def run_arm(service, qs: list[str], cache: bool, path: Path) -> None:
    from app.config import settings
    from app.services import tracing

    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    settings.cache_enabled = cache
    settings.groq_temperature = None
    settings.trace_enabled, settings.trace_path = True, path
    tracing.reset_trace_writer()
    service._cache.clear()
    for i, q in enumerate(qs, 1):
        for attempt in range(5):
            try:
                service.ask(q, mode="week4", trace_extra={"user": {"user": "user", "role": "chatbot", "session_id": "cost-exp"}})
                break
            except Exception as exc:  # noqa: BLE001 - 429s are routine on the free tier
                wait = 25 * (attempt + 1)
                print(f"  req {i}: {type(exc).__name__}, retrying in {wait}s", flush=True)
                time.sleep(wait)
        else:
            print(f"  req {i}: gave up", flush=True)
        time.sleep(1.0)
    print(f"cache={'on' if cache else 'off'}: {len(qs)} requests -> {path}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["organic", "faq"], default="faq")
    ap.add_argument("--n", type=int, default=30, help="organic only")
    a = ap.parse_args()
    from app.services.rag_service import get_rag_service
    from cost_report import load, render, summarise

    service = get_rag_service()
    qs = questions(a.kind, a.n)
    norm = lambda q: " ".join(q.lower().split()).rstrip("?.! ")  # noqa: E731
    repeat = 1 - len({norm(q) for q in qs}) / len(qs)
    print(f"{a.kind}: {len(qs)} requests, repeat rate {100 * repeat:.0f}%", flush=True)
    run_arm(service, qs, False, OUT / f"{a.kind}_cache_off.jsonl")
    run_arm(service, qs, True, OUT / f"{a.kind}_cache_on.jsonl")
    off = summarise(load(OUT / f"{a.kind}_cache_off.jsonl"))
    on = summarise(load(OUT / f"{a.kind}_cache_on.jsonl"))
    (OUT / f"{a.kind}_summary.json").write_text(json.dumps({"repeat_rate": repeat, "off": off, "on": on}, indent=2))
    print(render(off, "cache OFF"), "\n")
    print(render(on, "cache ON"))
    print(f"\nsaving per request: {100 * (1 - on['mean_usd'] / off['mean_usd']):.1f}%")


if __name__ == "__main__":
    main()
