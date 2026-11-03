"""
Week 10: the triage squad, its hand-off ledger, and the failure injection.

No test here calls Groq: a scripted fake client answers each role by its system
prompt, and the workers are reached through FastAPI's TestClient, so an
injected failure is a real HTTP 500 from the real worker app.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services.ticket_reply_app.tickets import TICKETS
from app.services.triage_squad import race
from app.services.triage_squad.metering import Ledger, MeteredClient, QuotaExhausted, percentile
from app.services.triage_squad.orchestrator import (
    DECOMPOSE_HOP,
    DECOMPOSE_SYSTEM_PROMPT,
    SYNTHESIS_HOP,
    run_orchestrator,
)
from app.services.triage_squad.worker_api import POLICY_HOP, TRIAGE_HOP, FailureInjector, create_worker_app
from app.services.triage_squad.workers import (
    POLICY_SYSTEM_PROMPT,
    POLICY_TOOLS,
    TRIAGE_SYSTEM_PROMPT,
    TRIAGE_TOOLS,
    run_tool_loop,
)

CASE = {
    "ticket_id": "T017",
    "tier": "Priority",
    "tenure_days": 5,
    "refund_requested": True,
    "question": "I paid 1999 on the 2nd, the engineer never turned up. Do I get my money back?",
    "context": "Refund Policy: missed installation and not activated within 7 days: 100% refund of ₹1999.",
}


def _usage(p=100, c=10):
    return SimpleNamespace(prompt_tokens=p, completion_tokens=c, total_tokens=p + c)


def _text(content):
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=_usage())


def _tool_call(name, args, call_id="call_1"):
    tc = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    message = SimpleNamespace(content="", tool_calls=[tc])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=_usage())


class FakeGroq:
    """Answers each role by its system prompt; records what each role was offered."""

    def __init__(self):
        self.offered = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        messages = kw["messages"]
        system = messages[0]["content"]
        done = [m["name"] for m in messages if m["role"] == "tool"]
        if system == DECOMPOSE_SYSTEM_PROMPT:
            return _text('{"triage_brief": "refund for missed install, repeated contact", "policy_query": "missed install refund"}')
        if system == TRIAGE_SYSTEM_PROMPT:
            self.offered["triage"] = [t["function"]["name"] for t in kw["tools"]]
            if not done:
                return _tool_call("lookup_order_record", {"ticket_id": "T017"})
            if done == ["lookup_order_record"]:
                return _tool_call("escalate_ticket", {"ticket_id": "T017", "reason": "missing_order", "severity": "high"})
            return _text('{"escalated": true, "account_facts": "Paid 1999, not activated, 3 missed visits."}')
        if system == POLICY_SYSTEM_PROMPT:
            self.offered["policy"] = [t["function"]["name"] for t in kw["tools"]]
            if not done:
                return _tool_call("retrieve_kb_context", {"query": "missed install refund"})
            passages = json.loads(messages[-1]["content"])["passages"]
            return _text(json.dumps({"answerable": True, "policy_text": passages}))
        # generate_ticket_reply: echo what it was given so tests can see the context.
        return _text("[Ticket #T017] " + messages[-1]["content"][:200])


@pytest.fixture
def squad():
    fake = FakeGroq()
    injector = FailureInjector()
    app = create_worker_app(fake, "fake-model", {CASE["ticket_id"]: CASE["context"]}, injector)
    with TestClient(app) as http:
        yield fake, injector, http


def test_squad_runs_end_to_end_and_every_hop_is_in_the_ledger(squad):
    fake, _, http = squad
    result = run_orchestrator(CASE, MeteredClient(fake, Ledger()), "fake-model", http)

    assert result["reply"].startswith("[Ticket #T017]")
    assert result["degraded"] == []
    hops = {c["hop"] for c in result["calls"]}
    assert hops == {DECOMPOSE_HOP, TRIAGE_HOP, POLICY_HOP, SYNTHESIS_HOP}
    # Worker tokens travel back over HTTP, so the total covers every call.
    assert result["total_tokens"] == sum(c["total_tokens"] for c in result["calls"])
    assert result["total_tokens"] == 110 * len(result["calls"])
    # The escalation note comes from the tool result, not the model's retelling.
    assert "Field Service Supervisor" in result["escalation_note"]
    assert "100% refund of ₹1999" in result["synthesis_context"]


def test_each_worker_is_offered_only_its_own_tools(squad):
    fake, _, http = squad
    run_orchestrator(CASE, MeteredClient(fake, Ledger()), "fake-model", http)
    assert set(fake.offered["triage"]) == set(TRIAGE_TOOLS)
    assert set(fake.offered["policy"]) == set(POLICY_TOOLS)


def test_a_worker_cannot_call_a_tool_outside_its_set():
    calls = []
    replies = iter([_tool_call("generate_ticket_reply", {"ticket_id": "T017"}), _text("{}")])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: next(replies))))
    _, results = run_tool_loop(client, "m", "sys", "user", POLICY_TOOLS, lambda n, a: calls.append(n) or {})
    assert calls == []
    assert "not available" in results[0]["result"]["error"]


def test_injected_500_is_retried_once_then_the_run_degrades(squad):
    fake, injector, http = squad
    injector.policy_fail_on = {"T017"}
    result = run_orchestrator(CASE, MeteredClient(fake, Ledger()), "fake-model", http)

    assert injector.hits == {"T017": 2}
    assert [a["status"] for a in result["policy"]["attempts"]] == [500, 500]
    assert result["degraded"] == ["policy"]
    assert "Policy lookup unavailable" in result["synthesis_context"]
    assert "₹1999" not in result["synthesis_context"].split("Account record")[0]
    failed = [c for c in result["calls"] if c["kind"] == "hand-off"]
    assert [c["status"] for c in failed] == ["http_500", "http_500"]
    assert all(c["total_tokens"] == 0 for c in failed)
    assert POLICY_HOP not in {c["hop"] for c in result["calls"] if c["kind"] != "hand-off"}


def test_metered_client_waits_out_a_429_and_records_it():
    attempts = iter([RuntimeError("Error code: 429 - Please try again in 0.01s"), _text("ok")])

    def create(**kw):
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    client = MeteredClient(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    client.chat.completions.create(model="m", messages=[])
    assert client.ledger.records[0]["rate_limit_wait_ms"] > 0
    assert client.ledger.total_tokens == 110


def test_metered_client_gives_up_on_a_daily_cap_wait():
    def create(**kw):
        raise RuntimeError("Error code: 429 - Please try again in 12m30s")

    client = MeteredClient(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    with pytest.raises(QuotaExhausted) as info:
        client.chat.completions.create(model="m", messages=[])
    assert client.quota_exhausted
    # The Week 7 code retries anything whose text says 429; this must not look like one.
    assert "429" not in str(info.value)


def test_p99_of_ten_is_the_slowest_and_p50_is_nearest_rank():
    values = [float(v) for v in range(1, 11)]
    assert percentile(values, 99) == 10.0
    assert percentile(values, 50) == 5.0


def test_race_cases_are_the_week6_records_for_the_week7_ids():
    cases = race.load_cases()
    assert [c["ticket_id"] for c in cases] == [t["ticket_id"] for t in TICKETS]
    assert len(cases) == 10
    # Read from the Week-6 eval set, not Week 7's copy (which has T010 at 0 days).
    assert next(c for c in cases if c["ticket_id"] == "T010")["tenure_days"] == 42


def test_multiplier_names_the_largest_handoff():
    def run(hop_tokens):
        return {"calls": [{"hop": h, "kind": "completion", "prompt_tokens": t - 10, "completion_tokens": 10,
                           "total_tokens": t} for h, t in hop_tokens]}

    shares = race.hop_shares([run([(POLICY_HOP, 600), (TRIAGE_HOP, 300), (SYNTHESIS_HOP, 100)])])
    assert shares[0]["hop"] == POLICY_HOP and shares[0]["share"] == pytest.approx(0.6)
    line = race.multiplier_line({"total_tokens": 400}, {"total_tokens": 1000}, shares[0])
    assert "**2.5x**" in line and POLICY_HOP in line and "60%" in line


class _GroqToolUseFailed(Exception):
    def __init__(self, generation):
        super().__init__("Error code: 400 - tool_use_failed")
        self.status_code = 400
        self.body = {"error": {"code": "tool_use_failed", "failed_generation": generation}}


def test_a_final_answer_sent_as_a_made_up_tool_call_is_recovered():
    """gpt-oss sometimes 'calls' a tool named json with its answer; Groq rejects the turn with a 400."""
    generation = json.dumps({"name": "json", "arguments": {"answerable": True, "policy_text": "Full refund of ₹1199."}})

    def create(**kw):
        raise _GroqToolUseFailed(generation)

    client = MeteredClient(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    text, _ = run_tool_loop(client, "m", "sys", "user", POLICY_TOOLS, lambda n, a: {})
    assert json.loads(text)["policy_text"] == "Full refund of ₹1199."
    # The rejected call is still in the ledger, with its tokens unknown.
    assert [c["kind"] for c in client.ledger.records] == ["rejected"]


def test_a_rejected_call_to_a_real_tool_still_fails():
    generation = json.dumps({"name": "retrieve_kb_context", "arguments": {"query": 3}})

    def create(**kw):
        raise _GroqToolUseFailed(generation)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(_GroqToolUseFailed):
        run_tool_loop(client, "m", "sys", "user", POLICY_TOOLS, lambda n, a: {})


def test_report_route_serves_the_saved_race_read_only():
    from app.main import app
    from app.services.triage_squad import report

    if not report.RESULTS.exists():
        pytest.skip("no saved Week 10 race in eval/week10/")
    client = TestClient(app)  # no lifespan: the route must not need the RAG index
    body = client.get("/api/week10/report").json()
    assert body["available"] is True
    assert [t["ticket_id"] for t in body["tickets"]] == [t["ticket_id"] for t in TICKETS]
    assert set(body["arms"]) == {"single", "multi"}
    for arm in body["arms"].values():
        assert {"passes", "p50_ms", "p99_ms", "total_tokens", "cost_per_ticket"} <= set(arm)
    # The page and race_table.md come from the same functions, so they cannot disagree.
    assert body["multiplier"]["line"] in (report.DOCS_DIR / "race_table.md").read_text("utf-8").replace("**", "")
    assert client.post("/api/week10/run").status_code in (404, 405)


def test_report_says_unavailable_before_any_race(tmp_path, monkeypatch):
    from app.services.triage_squad import report

    monkeypatch.setattr(report, "RESULTS", tmp_path / "missing.json")
    assert report.build_week10_report() == {"available": False}
