"""Metadata filtering and the two refusal layers, exercised against the real index."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import rag_service as rag_module
from app.services.rag_service import VectorStore, build_chunks, get_rag_service

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_documents"


@pytest.fixture(scope="module")
def store() -> VectorStore:
    """The winning configuration from results.md, built once for the module."""
    chunks = build_chunks(str(SAMPLE_ROOT), chunk_size=1000, overlap=100, strategy="heading")
    vector_store = VectorStore()
    vector_store.index(chunks)
    return vector_store


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _upload_corpus(client: TestClient) -> None:
    files = []
    for path in sorted(SAMPLE_ROOT.rglob("*")):
        if path.suffix.lower() in {".md", ".txt"}:
            relative = path.relative_to(SAMPLE_ROOT).as_posix()
            files.append(("files", (relative, path.read_bytes(), "text/markdown")))
    response = client.post("/api/documents/upload", files=files)
    assert response.status_code == 200, response.text


# --- filtering -----------------------------------------------------------------


def test_filter_restricts_results_to_the_requested_area(store: VectorStore):
    results = store.search("What is the 500 rupee charge for?", top_k=5, filters={"product_area": "installation"})
    assert results
    assert {chunk.product_area for chunk, _ in results} == {"installation"}


def test_filter_changes_the_ranking(store: VectorStore):
    question = "What are the speed test rules?"
    unfiltered = store.search(question, top_k=5)
    filtered = store.search(question, top_k=5, filters={"product_area": "billing"})
    assert [c.source for c, _ in unfiltered] != [c.source for c, _ in filtered]
    assert any(c.product_area != "billing" for c, _ in unfiltered)
    assert all(c.product_area == "billing" for c, _ in filtered)


def test_empty_filter_is_equivalent_to_no_filter(store: VectorStore):
    question = "How do I pay my bill?"
    assert [c.chunk_id for c, _ in store.search(question, top_k=5)] == [
        c.chunk_id for c, _ in store.search(question, top_k=5, filters={"product_area": ""})
    ]


def test_filter_with_no_matching_chunks_returns_nothing(store: VectorStore):
    assert store.search("anything at all", top_k=5, filters={"product_area": "no-such-area"}) == []


def test_filter_accepts_multiple_values(store: VectorStore):
    results = store.search(
        "What does it cost?", top_k=5, filters={"product_area": ["billing", "plans"]}
    )
    assert results
    assert {chunk.product_area for chunk, _ in results} <= {"billing", "plans"}


def test_filtering_is_exact_not_an_overfetch_window(store: VectorStore):
    """
    A filtered search must reach chunks ranked far down the unfiltered list.

    `account` chunks rank low for a troubleshooting query, so this only passes if
    the filter searches the whole corpus rather than post-filtering a top-k slice.
    """
    results = store.search(
        "Why does my router keep blinking red?", top_k=3, filters={"product_area": "account"}
    )
    assert results
    assert all(chunk.product_area == "account" for chunk, _ in results)


def test_chat_endpoint_accepts_a_product_area_filter(client: TestClient, monkeypatch):
    _upload_corpus(client)
    captured: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["prompt"] = kwargs["messages"][-1]["content"]

            class Message:
                content = "Installation costs 500 rupees (source: installation_setup.md)."

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class FakeClient:
        class chat:
            completions = FakeCompletions()

    service = get_rag_service()
    previous = service.client
    service.client = FakeClient()
    monkeypatch.setattr(rag_module.settings, "groq_api_key", "test-key")
    try:
        response = client.post(
            "/api/chat",
            json={"message": "What is the 500 rupee charge for?", "product_area": "installation"},
        )
        assert response.status_code == 200, response.text
        sources = response.json()["sources"]
        assert sources
        assert {s["product_area"] for s in sources} == {"installation"}
        assert all(s["article_id"] == "KB-005" for s in sources)
    finally:
        service.client = previous


def test_documents_endpoint_exposes_metadata(client: TestClient):
    _upload_corpus(client)
    body = client.get("/api/documents").json()
    assert "troubleshooting" in body["product_areas"]
    row = next(r for r in body["metadata"] if r["source_file"].endswith("troubleshooting_connectivity.md"))
    assert row["article_id"] == "KB-004"
    assert row["last_updated"] == "2026-08-10"
    assert row["chunks"] > 0


# --- refusal -------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "What is the capital of Mongolia?",
        "Who won the 2022 FIFA World Cup?",
    ],
)
def test_clearly_unrelated_questions_are_refused_before_the_llm(store: VectorStore, question: str):
    results = store.search(question, top_k=5)
    best = results[0][1] if results else 0.0
    assert best < rag_module.SCORE_THRESHOLD, f"{question!r} scored {best:.3f}"


def test_near_miss_question_gets_past_the_threshold(store: VectorStore):
    """
    Documents a known limitation measured in results.md section 5.

    'Reset my Netflix password' scores 0.310 - above every threshold that still
    keeps vaguely-worded in-corpus questions - so it reaches the LLM and only
    the grounding instruction in the system prompt refuses it. This test exists
    so that the prompt-level refusal is never deleted as redundant, and so a
    corpus or model change that alters the overlap is noticed.
    """
    results = store.search("How do I reset my Netflix password?", top_k=5)
    assert results
    assert results[0][1] > rag_module.SCORE_THRESHOLD


@pytest.mark.parametrize(
    "question",
    [
        "What are the benefits of the AirFiber_1199_1M plan?",
        "What should I do about error code AF-503?",
        "How long does an approved refund take to be credited?",
        "What do I need ready before the installation engineer arrives?",
        "What is the 500 rupee charge for?",
        "How do I raise a ticket?",
        "What are the speed test rules?",
    ],
)
def test_in_corpus_questions_survive_the_threshold(store: VectorStore, question: str):
    """
    Every in-corpus question must stay above the threshold, including the
    loosely-worded ones. A threshold tuned only on well-formed questions refuses
    these, which is why results.md settles on a recall-favouring value.
    """
    results = store.search(question, top_k=5)
    assert results
    assert results[0][1] >= rag_module.SCORE_THRESHOLD, f"{question!r} scored {results[0][1]:.3f}"


def test_refusal_string_is_returned_without_calling_the_llm(store: VectorStore):
    from app.services.rag_service import answer_with_groq

    results = store.search("What is the capital of Mongolia?", top_k=5)
    # client=None proves no LLM call happens on this path.
    answer = answer_with_groq(None, "unused-model", "What is the capital of Mongolia?", results)
    assert answer == "I don't know. That isn't covered in the documents I have."


def test_empty_llm_content_falls_back_to_refusal(store: VectorStore):
    """Groq returned empty content on weak context; a blank answer must not reach the user."""
    from app.services.rag_service import answer_with_groq

    class FakeCompletions:
        def create(self, **kwargs):
            class Message:
                content = "   "

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class FakeClient:
        class chat:
            completions = FakeCompletions()

    results = store.search("What are the benefits of the AirFiber_1199_1M plan?", top_k=5)
    assert results and results[0][1] >= rag_module.SCORE_THRESHOLD
    answer = answer_with_groq(FakeClient(), "unused-model", "anything", results)
    assert answer == "I don't know based on the provided documents."
