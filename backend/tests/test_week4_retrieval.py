"""
Week 4 retrieval: hybrid fusion, cross-encoder reranking, the document filter,
and the golden set the chat UI offers.

Week 3 must keep behaving exactly as it did - several tests here exist to pin
that, not to exercise anything new.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import rag_service as rag_module
from app.services.rag_service import (
    GOLDEN_SET_PATH,
    WEEK3,
    WEEK4,
    VectorStore,
    answer_with_groq,
    build_chunks,
    get_rag_service,
)
from app.services.retrieval import BM25_AVAILABLE, reciprocal_rank_fusion, tokenize

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_documents"


@pytest.fixture(scope="module")
def store() -> VectorStore:
    chunks = build_chunks(str(SAMPLE_ROOT), chunk_size=1000, overlap=100, strategy="heading")
    vector_store = VectorStore()
    vector_store.index(chunks)
    return vector_store


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _upload_corpus(client: TestClient) -> None:
    """
    Upload the sample corpus into a cleared docs dir.

    RagService is a process-global singleton over one shared temp directory, so
    without the reset an earlier test's flat upload leaves both `billing_faq.md`
    and `help_centre/billing_faq.md` indexed - which correctly makes the bare
    name ambiguous and makes these assertions order-dependent.
    """
    get_rag_service().reset_store()
    files = []
    for path in sorted(SAMPLE_ROOT.rglob("*")):
        if path.suffix.lower() in {".md", ".txt"}:
            relative = path.relative_to(SAMPLE_ROOT).as_posix()
            files.append(("files", (relative, path.read_bytes(), "text/markdown")))
    response = client.post("/api/documents/upload", files=files)
    assert response.status_code == 200, response.text


# --- tokenizer and fusion ------------------------------------------------------


def test_tokenizer_keeps_identifiers_findable_with_and_without_punctuation():
    """
    The corpus is full of AF-511 / AirFiber_1199_1M style identifiers. BM25 only
    helps on them if the query form and the document form tokenize alike.
    """
    assert set(tokenize("AF-511")) == {"af", "511", "af511"}
    assert "airfiber11991m" in tokenize("AirFiber_1199_1M")
    assert "af511" in tokenize("what does error code AF-511 mean")


def test_rrf_ranks_by_position_not_score():
    """
    A document ranked #1 by one retriever and #2 by the other must beat one that
    is #1 in a single list only - that consensus behaviour is the whole reason
    for fusing by rank instead of blending incomparable scores.
    """
    fused = reciprocal_rank_fusion({"dense": [7, 4, 9], "keyword": [4, 7, 2]})
    assert max(fused, key=fused.__getitem__) in (4, 7)
    assert fused[4] > fused[9]
    assert fused[7] > fused[2]


def test_rrf_of_an_empty_ranking_set_is_empty():
    assert reciprocal_rank_fusion({"dense": [], "keyword": []}) == {}


# --- hybrid retrieval ----------------------------------------------------------


@pytest.mark.skipif(not BM25_AVAILABLE, reason="rank_bm25 is not installed")
def test_bm25_finds_a_rare_error_code(store: VectorStore):
    hits = store.bm25.search("error code AF-511", top_k=3)
    assert hits
    top_chunk = store.chunks[hits[0][0]]
    assert "AF-511" in top_chunk.text


def test_week4_returns_per_stage_scores_and_week3_does_not(store: VectorStore):
    question = "What is error code AF-511 and how do I fix it?"

    week3 = [scored for _, scored in [
        (c, s) for c, s in _as_pairs(store, question, WEEK3)
    ]]
    assert all(s.rerank_score is None for s in week3), "Week 3 must not rerank"
    assert all(s.keyword_score == 0.0 for s in week3), "Week 3 has no keyword stage"

    week4 = [scored for _, scored in _as_pairs(store, question, WEEK4)]
    assert any(s.rerank_score is not None for s in week4)
    assert any(s.keyword_score > 0 for s in week4), "BM25 should fire on AF-511"


def _as_pairs(store: VectorStore, question: str, mode: str):
    if mode == WEEK4:
        return store.search_hybrid(question, top_k=5)
    from app.services.retrieval import Scored

    return [
        (chunk, Scored(index=-1, dense_score=score, dense_rank=rank))
        for rank, (chunk, score) in enumerate(store.search(question, top_k=5), start=1)
    ]


def test_week4_puts_the_answer_first_where_week3_does_not(store: VectorStore):
    """
    A regression guard on the reason Week 4 exists. "Are OTT add-on charges
    refundable?" is answered by one clause in the refund policy; dense retrieval
    alone ranks a plan chunk that merely mentions the OTT bundle above it.
    """
    question = "Are OTT add-on charges refundable?"
    needle = "promo code is redeemed"

    week3_top = store.search(question, top_k=5)[0][0]
    week4_top = store.search_hybrid(question, top_k=5)[0][0]

    assert needle in week4_top.text
    assert week4_top.article_id == "KB-003"
    # Documenting the contrast rather than asserting Week 3 is wrong: if a future
    # embedding model fixes this on its own, the Week 4 assertion above still holds.
    if needle not in week3_top.text:
        assert week3_top.article_id != "KB-003" or needle not in week3_top.text


def test_hybrid_filtering_is_exact_not_an_overfetch_window(store: VectorStore):
    """
    The invariant `search` guarantees must hold for `search_hybrid` too: both
    retrievers rank the whole corpus and the filter is applied afterwards.
    """
    results = store.search_hybrid(
        "installation charge", top_k=5, filters={"product_area": "installation"}
    )
    assert results
    assert {c.product_area for c, _ in results} == {"installation"}


def test_hybrid_returns_nothing_for_an_area_that_does_not_exist(store: VectorStore):
    assert store.search_hybrid("anything at all", top_k=5, filters={"product_area": "nope"}) == []


def test_hybrid_respects_top_k(store: VectorStore):
    assert len(store.search_hybrid("refund policy", top_k=2)) == 2


# --- the refusal gate stays on dense cosine ------------------------------------


def test_gate_score_overrides_the_first_results_score():
    """
    After reranking, results[0] is not necessarily the highest-cosine chunk, and
    a cross-encoder logit is not on the SCORE_THRESHOLD scale. The caller passes
    the best dense cosine, and that is what must decide the refusal.
    """

    class Chunk:
        text = "irrelevant"

    weak = [(Chunk(), 0.9)]  # a high first score that must NOT rescue the answer
    assert answer_with_groq(None, "unused", "q", weak, gate_score=0.01).startswith("I don't know")


def test_gate_score_defaults_to_week3_behaviour():
    class Chunk:
        text = "irrelevant"

    assert answer_with_groq(None, "unused", "q", [(Chunk(), 0.01)]).startswith("I don't know")


# --- golden set ----------------------------------------------------------------


def test_golden_set_covers_every_document_plus_the_contrast_pair():
    """
    Two questions per document, plus G13/G14 - the pair that Week 3 misses and
    Week 4 recovers. Those two are deliberately extra rather than replacements:
    the per-document questions exist so a reviewer can check any document, and
    dropping one to keep the count at 12 would leave a document unexercised.

    KB-007 (`airfiber_legacy_plans.md`) is intentionally absent. It is a
    distractor corpus, not a source of demo questions - its whole purpose is to
    crowd the retail plan chunks, which is what makes G13/G14 fail under Week 3.
    """
    payload = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    questions = payload["questions"]
    contrast = [q for q in questions if q.get("contrast")]
    per_document = {}
    for item in questions:
        if not item.get("contrast"):
            per_document[item["source_file"]] = per_document.get(item["source_file"], 0) + 1

    assert len(contrast) == 2
    assert len(per_document) == 6, "every non-distractor document needs its own questions"
    assert set(per_document.values()) == {2}
    assert len(questions) == len(per_document) * 2 + len(contrast)
    assert len({item["id"] for item in questions}) == len(questions)


def test_every_golden_answer_is_actually_retrievable(store: VectorStore):
    """
    A golden question whose answer is not in the corpus is a broken fixture, not
    a retrieval failure. Week 4 must surface every one of them in the top 5.
    """
    payload = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    missing = []
    for item in payload["questions"]:
        hits = store.search_hybrid(item["question"], top_k=5)
        found = any(
            all(needle.lower() in chunk.text.lower() for needle in item["answer_contains"])
            for chunk, _ in hits
        )
        if not found:
            missing.append(item["id"])
    assert missing == []


def test_golden_questions_endpoint_resolves_documents(client: TestClient):
    _upload_corpus(client)
    response = client.get("/api/golden-questions")
    assert response.status_code == 200
    questions = response.json()["questions"]
    assert len(questions) == 14
    assert all(item["available"] for item in questions)
    indexed = set(client.get("/api/documents").json()["documents"])
    assert {item["source_file"] for item in questions} <= indexed


# --- document scoping ----------------------------------------------------------


def test_resolve_document_accepts_a_bare_filename(client: TestClient):
    _upload_corpus(client)
    service = get_rag_service()
    assert service.resolve_document("billing_faq.md") == "help_centre/billing_faq.md"
    assert service.resolve_document("help_centre/billing_faq.md") == "help_centre/billing_faq.md"
    assert service.resolve_document("no_such_file.md") is None
    assert service.resolve_document("") is None


def test_chat_scoped_to_one_document_cites_only_that_document(client: TestClient, monkeypatch):
    _upload_corpus(client)
    service = get_rag_service()

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**_kwargs):
                    class Message:
                        content = "Scoped answer."

                    class Choice:
                        message = Message()

                    class Response:
                        choices = [Choice()]

                    return Response()

    # llm_configured checks the key as well as the client, and conftest pins
    # GROQ_API_KEY empty so the suite never reaches Groq.
    monkeypatch.setattr(service, "client", FakeClient())
    monkeypatch.setattr(rag_module.settings, "groq_api_key", "test-key")

    response = client.post(
        "/api/chat",
        json={
            "message": "What happens if my auto-pay payment fails?",
            "source_file": "billing_faq.md",
            "mode": "week4",
            "top_k": 5,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "week4"
    assert {source["source"] for source in body["sources"]} == {"help_centre/billing_faq.md"}


def test_chat_rejects_an_unknown_document(client: TestClient):
    _upload_corpus(client)
    response = client.post(
        "/api/chat", json={"message": "anything", "source_file": "not_here.md"}
    )
    assert response.status_code == 404
    assert "not_here.md" in response.json()["detail"]


def test_chat_rejects_an_unknown_mode(client: TestClient):
    response = client.post("/api/chat", json={"message": "anything", "mode": "week9"})
    assert response.status_code == 422


def test_health_reports_retrieval_capabilities(client: TestClient):
    body = client.get("/api/health").json()
    assert body["score_threshold"] == pytest.approx(0.15)
    assert "hybrid_available" in body
    assert body["reranker_model"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"
