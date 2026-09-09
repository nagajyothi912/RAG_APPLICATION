"""
Tests for the Week 5 request trace log.

Each of these guards a failure that is silent otherwise: a trace file that looks
complete but cannot be replayed, a schema that quietly drops the one field that
distinguished two failure modes, or a write path that turns a good answer into a
500. The taxonomy in docs/week5/ is only as trustworthy as the records it was
read from, so the schema is pinned here rather than assumed.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import rag_service as rag_module
from app.services import tracing
from app.services.rag_service import get_rag_service

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_documents"


def _file_tuple(path: Path):
    return (path.name, path.read_bytes(), "text/markdown")


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    """Deliberately carries no `finish_reason`, like the suite's other fakes."""

    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    """Deliberately carries no `usage`."""

    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class RecordingCompletions:
    def __init__(self, content="200 Mbps unlimited (source: airfiber_plans.md)."):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.content)


def _fake_client(completions):
    chat = type("FakeChat", (), {"completions": completions})()
    return type("FakeClient", (), {"chat": chat})()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def indexed(client, monkeypatch):
    """A one-article corpus with a stubbed LLM. Returns the recorder."""
    path = SAMPLE_ROOT / "help_centre" / "airfiber_plans.md"
    client.post("/api/documents/upload", files=[("files", _file_tuple(path))])
    completions = RecordingCompletions()
    service = get_rag_service()
    previous = service.client
    service.client = _fake_client(completions)
    monkeypatch.setattr(rag_module.settings, "groq_api_key", "test-key")
    yield completions
    service.client = previous


def test_tracing_is_off_by_default_and_a_chat_request_writes_nothing(client, indexed, tmp_path, monkeypatch):
    """
    The suite and both evaluation scripts must run without producing a byte of
    trace output. Tracing on by default would also mean evaluate_week4.py
    dumping four near-duplicate ablation records per question into the file the
    error analysis reads from.
    """
    path = tmp_path / "off.jsonl"
    monkeypatch.setattr(tracing, "_writer", tracing.TraceWriter(path=path, enabled=False))
    response = client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    assert response.status_code == 200, response.text
    assert not path.exists()
    assert response.json()["trace_id"] == ""


def test_a_chat_request_appends_exactly_one_parseable_json_line(client, indexed, traces):
    response = client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    assert response.status_code == 200, response.text
    records = traces()
    assert len(records) == 1
    assert records[0]["trace_id"] == response.json()["trace_id"]
    assert records[0]["schema_version"] == tracing.SCHEMA_VERSION
    assert records[0]["outcome"]["status"] == "answered"


def test_the_trace_records_every_retrieved_chunk_id_and_score_the_response_shows(client, indexed, traces):
    """
    The trace has to agree with what the user was shown, or the open coding is
    reading a different request from the one that happened.
    """
    response = client.post(
        "/api/chat", json={"message": "What does AirFiber_1199_1M include?", "mode": "week4"}
    )
    body = response.json()
    chunks = traces()[0]["retrieval"]["chunks"]
    assert [c["chunk_uid"] for c in chunks] == [
        f"{s['source']}#{s['chunk_id']}" for s in body["sources"]
    ]
    assert [c["dense_score"] for c in chunks] == [s["dense_score"] for s in body["sources"]]
    assert [c["rank"] for c in chunks] == list(range(1, len(chunks) + 1))


def test_the_trace_carries_the_exact_prompt_that_reached_the_model(client, indexed, traces):
    """
    This is the test that makes generation replay real rather than plausible.
    The user prompt interleaves format_citation() with chunk text, so anything
    that reconstructs it instead of recording it would drift the moment that
    function changed - and every trace already on disk would silently become
    unreplayable.
    """
    client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    sent = indexed.calls[-1]["messages"]
    generation = traces()[0]["generation"]
    assert generation["system_prompt"] == sent[0]["content"]
    assert generation["user_prompt"] == sent[1]["content"]
    assert generation["called"] is True
    assert generation["prompt_id"] == rag_module.PROMPT_ID


def test_the_trace_records_the_model_and_generation_params_verbatim(client, indexed, traces):
    client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    generation = traces()[0]["generation"]
    assert generation["model"] == rag_module.settings.groq_model
    assert generation["params"]["max_tokens"] == rag_module.MAX_TOKENS == 400
    assert generation["params"]["temperature"] == rag_module.settings.groq_temperature


def test_the_trace_keeps_the_raw_model_output_even_when_the_answer_was_replaced(
    client, indexed, traces
):
    """
    An all-whitespace completion is replaced by a refusal string the model never
    wrote. Without the raw output that case is indistinguishable from the
    pre-LLM gate, and the two need opposite fixes - which is exactly why
    CLAUDE.md insists the two refusal strings are never unified.
    """
    indexed.content = "   "
    response = client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    record = traces()[0]
    assert record["generation"]["raw_output"] == "   "
    assert record["generation"]["refusal"] == "empty_content"
    assert record["answer"]["source"] == "empty_fallback"
    assert response.json()["answer"] == "I don't know based on the provided documents."


def test_a_gate_refusal_is_traced_with_no_prompt_and_no_llm_call(client, indexed, traces):
    """
    Below SCORE_THRESHOLD the request never leaves the process. The trace has to
    say so, otherwise a refusal looks like a model decision when it was ours.
    """
    response = client.post("/api/chat", json={"message": "Who won the IPL in 2025?"})
    assert response.status_code == 200
    record = traces()[0]
    assert record["generation"]["called"] is False
    assert record["generation"]["system_prompt"] is None
    assert record["generation"]["refusal"] == "gate"
    assert record["answer"]["source"] == "gate_refusal"
    assert record["outcome"]["status"] == "refused"
    assert record["retrieval"]["refused"] is True
    assert indexed.calls == []


def test_a_generation_failure_is_traced_with_the_prompt_that_failed(client, indexed, traces):
    """
    The prompt is captured before the network call precisely so a 502 still
    records what was sent. A failed generation with no prompt is unreadable.
    """

    class Exploding:
        def create(self, **kwargs):
            raise RuntimeError("groq exploded")

    get_rag_service().client = _fake_client(Exploding())
    response = client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    assert response.status_code == 502
    record = traces()[0]
    assert record["outcome"]["status"] == "error"
    assert record["outcome"]["error_type"] == "RagGenerationError"
    assert record["generation"]["user_prompt"]
    assert record["answer"]["source"] == "none"


def test_a_request_before_any_documents_are_indexed_still_produces_a_trace(client, traces):
    """
    A 400 from an empty index is a real thing that happened to a real user, and
    it is invisible in a trace file that only records successful answers.
    """
    get_rag_service().reset_store()
    response = client.post("/api/chat", json={"message": "anything"})
    assert response.status_code == 400
    record = traces()[0]
    assert record["outcome"]["status"] == "error"
    assert record["outcome"]["error_type"] == "NoDocumentsError"
    assert record["retrieval"]["chunks"] == []


def test_the_prompt_id_is_pinned_so_an_edit_cannot_change_the_prompt_silently():
    """
    PROMPT_VERSION is hand-bumped so traces group into readable cohorts;
    PROMPT_SHA is derived so the version cannot drift away from the strings it
    names. If this fails, someone edited a prompt template: bump the version,
    update the literal, and note it, because every trace already on disk was
    produced by the old prompt and must stay attributable to it.
    """
    assert rag_module.PROMPT_SHA == "cfc04156c4e7"
    assert rag_module.PROMPT_ID == f"{rag_module.PROMPT_VERSION}-{rag_module.PROMPT_SHA}"


def test_a_trace_write_failure_does_not_fail_the_request(client, indexed, tmp_path, monkeypatch):
    """Telemetry must degrade, not take the answer down with it."""

    class BrokenWriter(tracing.TraceWriter):
        def write(self, record):
            raise OSError("disk full")

    monkeypatch.setattr(tracing, "_writer", BrokenWriter(path=tmp_path / "x.jsonl", enabled=True))
    response = client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    assert response.status_code == 200, response.text
    assert "200 Mbps" in response.json()["answer"]


def test_the_writer_gives_up_after_repeated_failures_instead_of_logging_forever(tmp_path):
    writer = tracing.TraceWriter(path=tmp_path / "nested" / "t.jsonl", enabled=True)
    writer.path = tmp_path  # a directory: every open() will fail
    for _ in range(5):
        writer.write({"a": 1})
    assert writer._broken is True


def test_concurrent_requests_each_append_one_whole_line(client, indexed, traces):
    """
    The chat route is a sync def, so Starlette runs it in a threadpool. Without
    a lock two 8 KB JSON lines interleave and the file stops parsing - which
    would be discovered only when the analysis tried to read it.
    """
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda i: client.post(
                    "/api/chat", json={"message": f"What does AirFiber_1199_1M include? {i}"}
                ),
                range(8),
            )
        )
    assert all(r.status_code == 200 for r in responses)
    records = traces()
    assert len(records) == 8
    assert len({r["trace_id"] for r in records}) == 8


def test_the_trace_records_enough_config_to_rebuild_the_index(client, indexed, traces):
    client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    config = traces()[0]["config"]
    for key in ("embed_model", "chunk_strategy", "chunk_size", "chunk_overlap", "score_threshold"):
        assert config[key] not in (None, ""), key
    assert config["corpus"]["chunks"] > 0
    assert config["corpus"]["fingerprint"]
    assert config["corpus"]["sources"]


def test_the_latency_fields_are_present_and_do_not_exceed_the_total(client, indexed, traces):
    client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    latency = traces()[0]["latency_ms"]
    assert latency["retrieval"] > 0
    assert latency["total"] > 0
    assert latency["retrieval"] + latency["generation"] <= latency["total"] + 1.0


def test_the_corpus_fingerprint_changes_when_the_corpus_does():
    """
    The fingerprint is the one comparison that tells a replay "the corpus moved"
    apart from "the retriever changed". If it were insensitive it would be worse
    than absent, because it would read as reassurance.
    """
    chunk = lambda src, cid, text: type(  # noqa: E731
        "C", (), {"source": src, "chunk_id": cid, "text": text}
    )()
    a = [chunk("a.md", 0, "hello"), chunk("a.md", 1, "world")]
    b = [chunk("a.md", 0, "hello"), chunk("a.md", 1, "world!")]
    assert tracing.corpus_fingerprint(a) == tracing.corpus_fingerprint(list(reversed(a)))
    assert tracing.corpus_fingerprint(a) != tracing.corpus_fingerprint(b)


# --------------------------------------------------------------- Langfuse sink

def test_langfuse_is_off_by_default_and_nothing_is_emitted(client, indexed, monkeypatch):
    """
    A developer with real Langfuse keys in backend/.env must not ship a trace to
    their live project on every test run. conftest pins LANGFUSE_ENABLED=false
    for the same reason it pins DOCS_DIR.
    """
    from app.services import langfuse_sink

    langfuse_sink.reset_client()
    assert langfuse_sink.enabled() is False
    calls = []
    monkeypatch.setattr(langfuse_sink, "emit", lambda *a, **k: calls.append(a))
    response = client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    assert response.status_code == 200
    assert calls == []


def test_the_langfuse_sink_consumes_the_same_record_the_jsonl_writer_does(client, indexed, traces, monkeypatch):
    """
    One record shape, two sinks. This is what makes the backfill script
    trustworthy: pushing the committed JSONL into Langfuse must produce exactly
    what a live request would have produced, not a second serialisation that
    drifts from the first.
    """
    from app.services import langfuse_sink
    from app.services import rag_service as rag_module

    captured = {}
    monkeypatch.setattr(langfuse_sink, "enabled", lambda: True)
    monkeypatch.setattr(langfuse_sink, "emit", lambda record, **k: captured.update(record))
    client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})

    written = traces()[0]
    assert captured["trace_id"] == written["trace_id"]
    assert captured["retrieval"]["chunks"] == written["retrieval"]["chunks"]
    assert captured["generation"]["user_prompt"] == written["generation"]["user_prompt"]


def test_a_langfuse_failure_does_not_fail_the_request(client, indexed, monkeypatch):
    """Telemetry degrades; the answer does not."""
    from app.services import langfuse_sink

    monkeypatch.setattr(langfuse_sink, "enabled", lambda: True)
    monkeypatch.setattr(langfuse_sink, "get_client", lambda: object())
    monkeypatch.setattr(
        langfuse_sink, "_emit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("langfuse down"))
    )
    langfuse_sink._broken = False
    response = client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    assert response.status_code == 200, response.text
    assert "200 Mbps" in response.json()["answer"]
    langfuse_sink._broken = False


def test_langfuse_trace_ids_are_derived_from_the_local_trace_id(monkeypatch):
    """
    Deterministic ids are what make the backfill re-runnable: a second push
    updates the same traces instead of duplicating 148 of them, and TR-0037 in
    the write-up resolves to one stable URL.
    """
    from app.services import langfuse_sink

    class FakeClient:
        def create_trace_id(self, *, seed):
            return "derived-" + seed

    monkeypatch.setattr(langfuse_sink, "get_client", lambda: FakeClient())
    first = langfuse_sink.trace_url("TR-0037")
    second = langfuse_sink.trace_url("TR-0037")
    assert first == second
    assert first.endswith("/trace/derived-TR-0037")
    assert langfuse_sink.trace_url("TR-0038") != first


def test_the_sink_never_tags_a_retrieval_mode_with_the_failure_mode_prefix(monkeypatch):
    """
    The Week 5 backfill tags each trace with the failure mode from taxonomy.md as
    `mode:1` ... `mode:5`. Which retriever ran is a different axis, and an earlier
    version emitted it as `mode:week4`, which put "week4" in the same filter list
    as "3" and read as a sixth failure mode. The prefixes must stay disjoint.
    """
    from app.services import langfuse_sink

    captured = {}

    class FakeSpan:
        def set_trace_io(self, **kwargs):
            return self

        def start_observation(self, **kwargs):
            return FakeSpan()

        def create_event(self, **kwargs):
            return self

        def update(self, **kwargs):
            return self

        def end(self, **kwargs):
            return self

    class FakeClient:
        def create_trace_id(self, *, seed):
            return "t-" + seed

        def start_observation(self, **kwargs):
            return FakeSpan()

    def fake_propagate(**kwargs):
        captured.update(kwargs)

        class Ctx:
            def __enter__(self):
                return None

            def __exit__(self, *a):
                return False

        return Ctx()

    import langfuse

    monkeypatch.setattr(langfuse, "propagate_attributes", fake_propagate)
    record = {
        "trace_id": "TR-0001",
        "schema_version": "1",
        "started_at": None,
        "finished_at": None,
        "pool": "random",
        "outcome": {"status": "answered", "error_message": None},
        "request": {
            "question": "q",
            "mode_effective": "week4",
            "top_k_effective": 5,
            "filters": {},
        },
        "config": {"corpus": {"fingerprint": "abc"}},
        "retrieval": {"chunks": [], "refused": False},
        "generation": {"called": False},
        "answer": {"text": "a", "source": "llm"},
        "latency_ms": {},
    }
    langfuse_sink._emit(FakeClient(), record, ["week5", "mode:3"])

    tags = captured["tags"]
    assert "retrieval:week4" in tags
    mode_tags = [t for t in tags if t.startswith("mode:")]
    assert mode_tags == ["mode:3"], mode_tags
    for tag in mode_tags:
        assert tag.split(":", 1)[1].isdigit(), f"{tag} is not a failure mode number"
