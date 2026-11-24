"""
Week 11: per-span cost/time in every trace, a searchable index over the log, the
exact-match answer cache, and the failure -> test suite.

Groq is never called: the client is a stub that reports token usage, so the cost
arithmetic is checked against numbers worked out by hand.
"""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import pricing, tracing
from app.services import rag_service as rag_module
from app.services.rag_service import get_rag_service
from app.services.trace_index import TraceIndex

BACKEND = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = BACKEND.parent / "sample_documents"
sys.path.insert(0, str(BACKEND / "scripts"))


class _Msg:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.message, self.finish_reason = _Msg(c), "stop"


class _Usage:
    prompt_tokens, completion_tokens, total_tokens = 1000, 100, 1100


class _Resp:
    def __init__(self, c):
        self.choices, self.usage = [_Choice(c)], _Usage()


class _Completions:
    def __init__(self, content="Refunds are available within 7 days of installation. (Source: refund_policy.txt)"):
        self.content, self.calls = content, 0

    def create(self, **kwargs):
        self.calls += 1
        return _Resp(self.content)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def refund_app(client, monkeypatch):
    for name in ("policies/refund_policy.txt",):
        p = SAMPLE_ROOT / name
        client.post("/api/documents/upload", files=[("files", (p.name, p.read_bytes(), "text/plain"))])
    comp = _Completions()
    svc = get_rag_service()
    prev = svc.client
    svc.client = type("C", (), {"chat": type("Ch", (), {"completions": comp})()})()
    monkeypatch.setattr(rag_module.settings, "groq_api_key", "k")
    svc._cache.clear()
    yield comp
    svc.client = prev
    svc._cache.clear()


# ---- per-span time and cost -------------------------------------------------

def test_cost_is_tokens_times_the_price_table():
    # 1000 in at $0.15/M + 100 out at $0.60/M = 0.00015 + 0.00006
    assert pricing.call_cost("openai/gpt-oss-120b", 1000, 100) == pytest.approx(0.00021)
    assert pricing.rates("some-unknown-model")[2] is True  # priced as the default, flagged estimated


def test_every_trace_has_per_span_latency_tokens_cost_and_context_ids(client, refund_app, traces):
    r = client.post("/api/chat", json={"message": "How many days do I have to ask for a refund?", "mode": "week4"})
    assert r.status_code == 200, r.text
    rec = traces()[0]
    spans = {s["name"]: s for s in rec["spans"]}
    assert {"retrieval", "generation"} <= set(spans)
    assert spans["generation"]["tokens_in"] == 1000 and spans["generation"]["tokens_out"] == 100
    assert spans["generation"]["cost_usd"] == pytest.approx(0.00021)
    assert spans["retrieval"]["cost_usd"] == 0.0 and spans["retrieval"]["latency_ms"] > 0
    assert spans["generation"]["start_ms"] >= spans["retrieval"]["latency_ms"] - 0.01  # stages run in sequence
    assert rec["cost_usd"]["total"] == pytest.approx(0.00021)
    assert rec["cost_usd"]["tools"] == 0.0
    assert rec["generation"]["prompt_version"] == rag_module.PROMPT_VERSION
    assert rec["context_ids"] == [c["chunk_uid"] for c in rec["retrieval"]["chunks"]]
    assert rec["session"]["user"] == "auth-disabled"  # AUTH_ENABLED=false in the suite
    assert rec["input_type"] == "question"


def test_spans_add_up_to_the_total_with_the_remainder_as_other():
    spans, _, _ = tracing.build_spans(
        latency_ms={"retrieval": 100.0, "generation": 900.0, "total": 1050.0},
        capture={}, follow_up=None, retrieval_attrs={}, cache_hit=False)
    assert [s["name"] for s in spans] == ["retrieval", "generation", "other"]
    assert spans[-1]["start_ms"] == 1000.0 and spans[-1]["latency_ms"] == 50.0
    assert sum(s["latency_ms"] for s in spans) == pytest.approx(1050.0)


def test_drill_records_finish_after_they_start():
    import random
    from datetime import datetime, timezone

    import week11_drill

    rec = week11_drill.make_record(
        when=datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc), question="q", answer="a",
        ctx=["refund_policy.txt#0"], user="user", session="s-1", prompt_version="v1",
        input_type="question", rng=random.Random(1), gen_ms=1000.0, retrieval_ms=200.0)
    assert rec["started_at"] == "2026-11-03T10:00:00.000Z"
    assert rec["finished_at"] == "2026-11-03T10:00:01.200Z"


def test_a_follow_up_is_tagged_and_its_rewrite_call_is_its_own_span(client, refund_app, traces):
    r = client.post("/api/chat", json={
        "message": "and how long does it take?",
        "history": [{"role": "user", "content": "Can I get a refund?"},
                    {"role": "assistant", "content": "Yes within 7 days."}]})
    assert r.status_code == 200, r.text
    rec = traces()[0]
    assert rec["input_type"] == "follow_up"
    names = [s["name"] for s in rec["spans"]]
    assert names[0] == "rewrite" and "generation" in names
    assert rec["cost_usd"]["rewrite"] > 0


# ---- the index --------------------------------------------------------------

def test_the_index_finds_a_refund_answer_by_its_words_its_context_and_its_cost(client, refund_app, traces, tmp_path):
    client.post("/api/chat", json={"message": "How many days do I have to ask for a refund?", "mode": "week4"})
    idx = tracing.get_trace_writer().path.parent / "trace_index.db"
    assert idx.exists(), "the index is written beside the log on every traced request"
    ti = TraceIndex(idx)
    assert len(ti.search(text="7 days")) == 1          # the answer's words
    assert len(ti.search(text="money back")) == 0
    assert len(ti.search(context="refund_policy.txt")) == 1  # retrieved context ids
    assert len(ti.search(min_cost=0.0001)) == 1 and ti.search(min_cost=1.0) == []
    assert ti.search(text='refund" OR "x')  is not None   # punctuation cannot break the query


def test_a_deleted_index_is_rebuilt_from_the_jsonl(client, refund_app, traces):
    client.post("/api/chat", json={"message": "How long do refunds take?", "mode": "week4"})
    log = tracing.get_trace_writer().path
    fresh = TraceIndex(log.parent / "rebuilt.db")
    assert fresh.rebuild(log) == 1 and fresh.count() == 1


def test_find_trace_rebuilds_a_stale_index_even_when_the_row_count_is_unchanged(tmp_path):
    """Found in the drill: a re-seeded log with the same number of lines was served from the old index."""
    import os
    import time
    from find_trace import ensure_index

    def rec(tid, answer):
        return {"event": "chat", "trace_id": tid, "started_at": "2026-11-03T10:00:00.000Z",
                "request": {"question": "q", "mode_effective": "week4"}, "answer": {"text": answer, "source": "llm"},
                "generation": {"prompt_version": "v1"}, "cost_usd": {"total": 0.0}, "latency_ms": {"total": 1.0},
                "outcome": {"status": "answered"}, "context_ids": []}

    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps(rec("a" * 12, "old answer")) + "\n")
    assert len(ensure_index(log).search(text="old")) == 1
    log.write_text(json.dumps(rec("b" * 12, "new answer")) + "\n")  # same line count
    os.utime(log, (time.time() + 5, time.time() + 5))
    idx = ensure_index(log)
    assert idx.search(text="old") == [] and len(idx.search(text="new")) == 1


def test_find_trace_reads_yesterday_afternoon_in_local_time():
    from find_trace import window
    since, until = window("2026-11-03", "12-18", 5.5)
    assert (since, until) == ("2026-11-03T06:30:00", "2026-11-03T12:30:00")


# ---- the cache --------------------------------------------------------------

def test_the_cache_serves_a_repeat_with_no_model_call_and_traces_it_as_free(client, refund_app, traces, monkeypatch):
    monkeypatch.setattr(rag_module.settings, "cache_enabled", True)
    q = "How many days do I have to ask for a refund?"
    first = client.post("/api/chat", json={"message": q, "mode": "week4"}).json()["answer"]
    second = client.post("/api/chat", json={"message": q.lower().rstrip("?") + "  ?", "mode": "week4"}).json()["answer"]
    assert second == first and refund_app.calls == 1
    a, b = traces()
    assert a["cache"]["hit"] is False and b["cache"]["hit"] is True
    assert b["answer"]["source"] == "cache" and b["cost_usd"]["total"] == 0.0
    assert b["trace_id"] != a["trace_id"], "a cache hit is still its own findable request"


def test_a_prompt_bump_or_new_document_stops_old_cache_entries_matching(client, refund_app, monkeypatch):
    monkeypatch.setattr(rag_module.settings, "cache_enabled", True)
    svc = get_rag_service()
    k1 = svc._cache_key("q", None, None, "week4")
    monkeypatch.setattr(rag_module, "PROMPT_ID", "v9-xxxx")
    assert svc._cache_key("q", None, None, "week4") != k1


def test_a_refusal_is_never_cached(client, refund_app, monkeypatch):
    monkeypatch.setattr(rag_module.settings, "cache_enabled", True)
    refund_app.content = "I don't know based on the provided documents."
    for _ in range(2):
        client.post("/api/chat", json={"message": "How many days do I have to ask for a refund?", "mode": "week4"})
    assert refund_app.calls == 2


def test_an_answer_the_model_was_cut_off_in_is_never_cached(client, refund_app, monkeypatch):
    """Found in the cost experiment: 10 of 28 organic answers hit the 400-token cap. Caching one would replay the truncation."""
    monkeypatch.setattr(rag_module.settings, "cache_enabled", True)
    original = _Choice.__init__

    def cut_off(self, c):
        original(self, c)
        self.finish_reason = "length"

    monkeypatch.setattr(_Choice, "__init__", cut_off)
    for _ in range(2):
        client.post("/api/chat", json={"message": "How many days do I have to ask for a refund?", "mode": "week4"})
    assert refund_app.calls == 2


# ---- the failure -> test loop ----------------------------------------------

def test_the_failure_case_is_in_the_suite_and_the_prompt_carries_the_fix():
    from run_week11_suite import load_cases
    cases = {c["id"]: c for c in load_cases()}
    assert {"F01", "F02"} <= set(cases) and len({c["id"] for c in load_cases()}) == len(cases)
    assert cases["F01"]["kind"] == "failure"
    assert rag_module.PROMPT_VERSION == "v2"
    assert "do not answer \"I don't know\"" in rag_module.SYSTEM_PROMPT


def test_the_suite_retrieval_checks_pass_on_the_sample_refund_policy(client, refund_app):
    """Deterministic half of the suite (no model call). Generation is run by scripts/run_week11_suite.py."""
    from run_week11_suite import check_case, load_cases
    svc = get_rag_service()
    refund_cases = [c for c in load_cases() if c["id"] in ("R01", "R02", "F01", "F02")]
    assert len(refund_cases) == 4
    for case in refund_cases:
        result = check_case(svc, case, generate=False)
        assert result["ok"], result["failures"]


def test_trace_to_case_makes_a_skeleton_that_cannot_pass_by_accident():
    from trace_to_case import skeleton
    rec = {"trace_id": "abc", "started_at": "t", "generation": {"prompt_version": "v1"},
           "request": {"question": "q?", "mode_effective": "week4"}, "answer": {"text": "bad"},
           "context_ids": ["refund_policy.txt#0"]}
    case = skeleton(rec, "F09")
    assert case["observed_bad_answer"] == "bad" and case["question"] == "q?"
    # Expectations are TODOs, never derived from the bad answer, so the case is RED until a person writes them.
    assert all(v[0].startswith("TODO") for v in (case["expect_chunks"], case["answer_matches"], case["answer_not_matches"]))
