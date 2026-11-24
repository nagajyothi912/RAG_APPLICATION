#!/usr/bin/env python3
"""
Support-drill setup: a log with thousands of requests and one planted bad answer.

    python scripts/week11_drill.py seed  [--n 3000] [--days 7]      # background traffic
    python scripts/week11_drill.py plant                            # squadmate: plant one
    python scripts/week11_drill.py reveal                           # after the timed run

The drill log is backend/data/traces/drill/chat_traces.jsonl, separate from the
real trace log, so practising never pollutes real data. Run `seed` once, then the
SQUADMATE runs `plant` (the finder must not know the time or the wording) and
starts the clock; the finder gets only the complaint text.

What is real and what is synthetic:
- `seed` traffic is SYNTHETIC: question/answer pairs written from the knowledge
  base, with token counts, latencies and costs drawn at random around the values
  measured on real requests. Every record is built by the app's own
  `tracing.build_chat_record`, so it has exactly the shape of a live trace, and
  is tagged pool="week11-drill".
- The planted trace is REAL: `plant` sends a refund question through the live
  pipeline with the Week 10 prompt (v1) and keeps the model's actual answer,
  usage and latency. Only the timestamp, trace id and user are rewritten.
  Needs GROQ_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

DRILL_DIR = BACKEND / "data" / "traces" / "drill"
LOG = DRILL_DIR / "chat_traces.jsonl"
SECRET = DRILL_DIR / "planted.secret.json"

# The Week 10 prompt, byte for byte, so `plant` produces a genuine v1 answer.
V1_SYSTEM_PROMPT = (
    "Answer ONLY using the provided context. Every answer must name "
    "the source file it came from. If the context does not contain "
    "the answer, say exactly: \"I don't know based on the provided "
    "documents.\" Never use outside knowledge."
)

# (question, answer, context ids). The answers are what the knowledge base says.
TRAFFIC = [
    ("How many days do I have to ask for a refund?", "You have 7 days from the first installation to request a refund. (Source: refund_policy.txt)", ["refund_policy.txt#0"], 5),
    ("Can I get a refund for the OTT add-on?", "No. Refunds are not available for OTT add-ons once the promo code is redeemed. (Source: refund_policy.txt)", ["refund_policy.txt#0", "airfiber_plans.md#3"], 4),
    ("Where will my refund be credited and when?", "Refunds go back to the original payment method within 10 business days. (Source: refund_policy.txt)", ["refund_policy.txt#0", "billing_faq.md#0"], 4),
    ("I'm on day 20, can I get a full refund?", "No. Refunds are only available within 7 days of first installation. (Source: refund_policy.txt)", ["refund_policy.txt#0", "account_management.md#4"], 3),
    ("how do I raise a refund request", "Open a ticket in the AirFiber app under Billing > Refund and attach the three speed-test screenshots. (Source: refund_policy.txt)", ["refund_policy.txt#0"], 3),
    ("What is the installation charge for the 599 plan?", "The AirFiber_599_1M plan carries a one-time installation charge of ₹500. (Source: installation_setup.md)", ["installation_setup.md#1", "airfiber_plans.md#2"], 6),
    ("my payment failed, will my internet stop?", "The service is not cut immediately; there is a 5-day grace period before speed drops to 2 Mbps. (Source: billing_faq.md)", ["billing_faq.md#2", "billing_faq.md#0"], 6),
    ("What OTT apps are included with the 1199 plan?", "Disney+ Hotstar, SonyLIV and Amazon Prime Video. (Source: airfiber_plans.md)", ["airfiber_plans.md#1", "airfiber_plans.md#4"], 5),
    ("my internet is slow in the evening", "Evening slowness is usually exchange port congestion; request a port reallocation. (Source: troubleshooting_connectivity.md)", ["troubleshooting_connectivity.md#3", "troubleshooting_connectivity.md#4"], 6),
    ("what do I need ready before the engineer comes", "A photo ID, a power socket within 2 metres of the ONT location and the 6-digit installation OTP. (Source: installation_setup.md)", ["installation_setup.md#0"], 4),
    ("how do I pause my connection", "You can suspend service temporarily from the app under Account. (Source: account_management.md)", ["account_management.md#3", "account_management.md#4"], 3),
    ("Can I keep recharging my grandfathered 1249 pack through UPI?", "Yes, grandfathered 1249 subscribers can recharge with UPI, NetBanking or cards. (Source: airfiber_legacy_plans.md)", ["airfiber_legacy_plans.md#0"], 2),
]
REFUSAL = "I don't know. That isn't covered in the documents I have."
OFF_TOPIC = ["What is the capital of France?", "write me a poem", "who won the match last night", "what's the weather"]


def _chunk(uid: str):
    source, cid = uid.split("#")
    return SimpleNamespace(source=source, chunk_id=int(cid), article_id="KB", product_area="x",
                           last_updated="2026-08-01", section="", text=f"{uid} text")


def _scored(rank: int, dense: float):
    return SimpleNamespace(index=-1, dense_score=dense, keyword_score=0.0, fused_score=0.03,
                           rerank_score=-2.0 - rank, dense_rank=rank, keyword_rank=None, retriever="both")


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def make_record(*, when: datetime, question: str, answer: str, ctx: list[str], user: str, session: str,
                prompt_version: str, input_type: str, rng: random.Random, tokens=None, gen_ms=None,
                retrieval_ms=None, refused=False, trace_id=None, rewrite=False) -> dict:
    from app.services import rag_service as rs
    from app.services import tracing

    p_tok = tokens[0] if tokens else int(rng.gauss(760, 140))
    c_tok = tokens[1] if tokens else max(15, int(rng.gauss(70, 30)))
    gen_ms = gen_ms if gen_ms is not None else max(250.0, rng.gauss(1100, 350))
    retrieval_ms = retrieval_ms if retrieval_ms is not None else max(40.0, rng.gauss(140, 40))
    results = [(_chunk(u), _scored(n + 1, 0.55 - 0.07 * n)) for n, u in enumerate(ctx)]
    capture = {} if refused else {
        "called": True, "prompt_id": f"{prompt_version}-drill", "prompt_version": prompt_version,
        "prompt_sha256": "drill", "model": rs.settings.groq_model, "refusal": None,
        "usage": {"prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": p_tok + c_tok},
        "api_latency_ms": gen_ms * 0.95, "finish_reason": "stop", "raw_output": answer,
        "context_chars": 900, "params": {"temperature": None, "max_tokens": 400},
    }
    follow_up = None
    if rewrite:
        follow_up = {"original_question": question, "history_messages": 2, "rewritten": True,
                     "model": rs.settings.groq_model, "error": None,
                     "usage": {"prompt_tokens": 210, "completion_tokens": 22, "total_tokens": 232},
                     "latency_ms": 420.0}
    total_ms = retrieval_ms + (0.1 if refused else gen_ms) + (420.0 if rewrite else 0)
    started = _stamp(when)
    rec = tracing.build_chat_record(
        trace_id=trace_id or uuid.uuid4().hex, started_at=started,
        finished_at=_stamp(when + timedelta(milliseconds=total_ms)), question=question,
        mode_requested="week4", mode_effective="week4", top_k_requested=None, top_k_effective=5, filters=None,
        config={"groq_base_url": rs.settings.groq_base_url}, results=results,
        gate_score=0.05 if refused else 0.5, score_threshold=0.15, hybrid=True, reranked=True,
        answer_text=answer, answer_source="gate_refusal" if refused else "llm", capture=capture, error=None,
        latency_ms={"retrieval": retrieval_ms, "generation": 0.1 if refused else gen_ms,
                    "total": total_ms},
        pool="week11-drill", user={"user": user, "role": "chatbot", "session_id": session},
        input_type=input_type, follow_up=follow_up,
    )
    return rec


def seed(n: int, days: int, seed_value: int, tz_offset: float) -> None:
    rng = random.Random(seed_value)
    DRILL_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    weights = [t[3] for t in TRAFFIC]
    records = []
    sessions = [f"s-{rng.randrange(10**6):06d}" for _ in range(60)]
    for _ in range(n):
        # Working-hours-heavy traffic: sample a day and an hour with a daytime bias.
        day = now - timedelta(days=rng.randrange(days) + (0 if rng.random() < 0.3 else 1))
        hour = min(23, max(0, int(rng.gauss(14, 4) - tz_offset)))
        when = day.replace(hour=hour, minute=rng.randrange(60), second=rng.randrange(60), microsecond=rng.randrange(10**6))
        if when > now:
            when -= timedelta(days=1)
        user = rng.choices(["user", "admin"], [0.85, 0.15])[0]
        session = rng.choice(sessions)
        roll = rng.random()
        if roll < 0.07:
            q = rng.choice(OFF_TOPIC)
            records.append(make_record(when=when, question=q, answer=REFUSAL, ctx=["airfiber_plans.md#0"], user=user,
                                       session=session, prompt_version="v1", input_type="question", rng=rng, refused=True,
                                       retrieval_ms=max(40.0, rng.gauss(130, 30))))
            continue
        q, a, ctx, _ = rng.choices(TRAFFIC, weights)[0]
        follow = roll > 0.85
        extra = {}
        if rng.random() < 0.02:  # the cost outliers: a long answer on a fat context
            extra = {"tokens": (int(rng.gauss(3400, 300)), int(rng.gauss(380, 20)))}
        records.append(make_record(when=when, question=q, answer=a, ctx=ctx, user=user, session=session,
                                   prompt_version="v1", input_type="follow_up" if follow else "question",
                                   rng=rng, rewrite=follow, **extra))
    records.sort(key=lambda r: r["started_at"])
    with open(LOG, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"seeded {len(records)} synthetic traces over {days} days -> {LOG}")


def plant(tz_offset: float, rng_seed: int | None) -> None:
    """Run a refund question through the live app on the v1 prompt and plant its real trace."""
    from app.config import settings
    from app.services import rag_service as rs
    from app.services import tracing

    settings.groq_temperature = None
    service = rs.get_rag_service()
    if not service.llm_configured:
        sys.exit("GROQ_API_KEY not set")
    rs.SYSTEM_PROMPT, rs.PROMPT_VERSION = V1_SYSTEM_PROMPT, "v1"
    rs.PROMPT_SHA = rs.hashlib.sha256((V1_SYSTEM_PROMPT + "\x00" + rs.USER_PROMPT_TEMPLATE).encode()).hexdigest()[:12]
    rs.PROMPT_ID = f"v1-{rs.PROMPT_SHA}"

    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "planted.jsonl"
    tracing.reset_trace_writer()
    settings.trace_enabled, settings.trace_path = True, tmp
    question = "does the 30 day money back guarantee apply to me"
    for _ in range(5):
        service.ask(question, mode="week4", trace_extra={"user": {"user": "user", "role": "chatbot", "session_id": None}})
        rec = json.loads(tmp.read_text().splitlines()[-1])
        if "don't know" in rec["answer"]["text"].lower():
            break
    rng = random.Random(rng_seed)
    # "Yesterday afternoon" is the squadmate's local day: work out the local date,
    # place the request at a local hour 12-18, then convert to UTC for the log.
    tz = timezone(timedelta(hours=tz_offset))
    local_day = (datetime.now(tz) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    when_local = local_day + timedelta(hours=rng.randrange(12, 18), minutes=rng.randrange(60), seconds=rng.randrange(60))
    when = when_local.astimezone(timezone.utc)
    when = when.replace(microsecond=0)
    stamp = _stamp(when)
    # Keep the request's real duration: finished_at = started_at + total latency.
    rec["started_at"] = stamp
    rec["finished_at"] = _stamp(when + timedelta(milliseconds=rec["latency_ms"]["total"]))
    rec["trace_id"] = uuid.uuid4().hex
    rec["session"]["session_id"] = f"s-{rng.randrange(10**6):06d}"
    rec["pool"] = "week11-drill"
    lines = [json.loads(l) for l in open(LOG, encoding="utf-8")]
    lines.append(rec)
    lines.sort(key=lambda r: r["started_at"])
    with open(LOG, "w", encoding="utf-8") as fh:
        for r in lines:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    SECRET.write_text(json.dumps({"trace_id": rec["trace_id"], "started_at": stamp, "question": question,
                                  "answer": rec["answer"]["text"], "prompt_version": rec["generation"]["prompt_version"]},
                                 indent=2), encoding="utf-8")
    print("planted 1 bad refund answer. Secret kept in", SECRET, "- do not open it. Start the clock.")


def reveal() -> None:
    print(SECRET.read_text())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed"); s.add_argument("--n", type=int, default=3000); s.add_argument("--days", type=int, default=7)
    s.add_argument("--seed", type=int, default=11); s.add_argument("--tz-offset", type=float, default=0.0)
    p = sub.add_parser("plant"); p.add_argument("--tz-offset", type=float, default=0.0); p.add_argument("--seed", type=int)
    sub.add_parser("reveal")
    a = ap.parse_args()
    if a.cmd == "seed":
        seed(a.n, a.days, a.seed, a.tz_offset)
    elif a.cmd == "plant":
        plant(a.tz_offset, a.seed)
    else:
        reveal()


if __name__ == "__main__":
    main()
