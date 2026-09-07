"""
Week 4 evaluation fixture and one-variable ablation.

The Week 4 report is only meaningful if two things hold: every gold label in
`golden_set.jsonl` really points at a chunk that answers the question, and each
arm in the comparison differs from the baseline by exactly one retrieval stage.
Both are silent failures - a stale label just moves a hit rate, and an ablation
flag that does not actually disable its stage would make the "exactly one
change" claim in results.md false while every number still looks plausible.
"""

import json
from pathlib import Path

import pytest

from app.services.rag_service import VectorStore, build_chunks
from app.services.retrieval import BM25_AVAILABLE

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_documents"
GOLDEN_SET = Path(__file__).resolve().parents[1] / "eval" / "golden_set.jsonl"

# The configuration the golden set's chunk ids were labelled against. Chunk ids
# are positional, so any other chunking makes every label meaningless.
STRATEGY, CHUNK_SIZE, OVERLAP = "heading", 1000, 100


@pytest.fixture(scope="module")
def golden():
    return [json.loads(line) for line in GOLDEN_SET.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def chunks_by_id():
    chunks = build_chunks(str(SAMPLE_ROOT), chunk_size=CHUNK_SIZE, overlap=OVERLAP, strategy=STRATEGY)
    return {f"{c.source}#{c.chunk_id}": c for c in chunks}


@pytest.fixture(scope="module")
def store(chunks_by_id):
    vector_store = VectorStore()
    vector_store.index(list(chunks_by_id.values()))
    return vector_store


def test_golden_set_has_twelve_questions_and_four_exact_identifiers(golden):
    """Both counts are assignment requirements, not preferences."""
    assert len(golden) == 12
    assert sum(row["exact_token"] for row in golden) >= 4


def test_golden_set_ids_and_questions_are_unique(golden):
    assert len({row["id"] for row in golden}) == 12
    assert len({row["question"] for row in golden}) == 12


# The six articles the 12-question golden set was written against. KB-007 was
# added afterwards, as a deliberate distractor corpus, and is intentionally not
# a question source: the golden set is a fixed 12 (an assignment requirement),
# and its labels must not drift every time the corpus grows.
GOLDEN_SET_ARTICLES = {"KB-001", "KB-002", "KB-003", "KB-004", "KB-005", "KB-006"}


def test_golden_set_covers_the_articles_it_was_written_against(golden, chunks_by_id):
    indexed = {c.article_id for c in chunks_by_id.values()}
    covered = {row["article_id"] for row in golden}
    assert covered == GOLDEN_SET_ARTICLES
    assert covered <= indexed, "a golden question points at an article no longer indexed"


def test_every_gold_label_points_at_a_chunk_that_answers_it(golden, chunks_by_id):
    """
    The load-bearing fixture check. A label that no longer contains its gold
    answer turns a passing question into a silent, permanent miss, and the
    hit-rate in results.md would move for a reason that has nothing to do with
    retrieval.
    """
    for row in golden:
        chunk = chunks_by_id.get(row["expected_chunk_id"])
        assert chunk is not None, f"{row['id']}: no chunk {row['expected_chunk_id']}"
        body = chunk.text.lower()
        missing = [fact for fact in row["answer_contains"] if fact.lower() not in body]
        assert not missing, f"{row['id']}: {row['expected_chunk_id']} is missing {missing}"


def test_gold_labels_agree_with_their_declared_article(golden, chunks_by_id):
    for row in golden:
        assert chunks_by_id[row["expected_chunk_id"]].article_id == row["article_id"]


def test_golden_set_is_separate_from_the_week3_gold_questions():
    """
    `gold_questions.json` drives sections 1-8 and `golden_set.jsonl` drives 9-14.
    Editing one must never move a number in the other, which only holds while
    they stay distinct files with distinct question text.
    """
    week3 = json.loads((GOLDEN_SET.parent / "gold_questions.json").read_text(encoding="utf-8"))
    week3_questions = {q["question"] for q in week3["known_answer"]}
    week4_questions = {json.loads(line)["question"] for line in GOLDEN_SET.read_text().splitlines() if line.strip()}
    assert not (week3_questions & week4_questions)


@pytest.mark.skipif(not BM25_AVAILABLE, reason="rank_bm25 not installed")
def test_use_keyword_false_actually_disables_bm25(store):
    """
    The ablation flag has to disable the stage, not merely deprioritise it.
    If it did not, the "cross-encoder only" arm in results.md would secretly be
    the two-change stack and the report's central claim would be false.
    """
    query = "app shows AF-511, what do I do?"
    with_bm25 = store.search_hybrid(query, top_k=5, rerank=False, use_keyword=True)
    without = store.search_hybrid(query, top_k=5, rerank=False, use_keyword=False)

    assert any(scored.keyword_rank is not None for _, scored in with_bm25)
    assert all(scored.keyword_rank is None for _, scored in without)
    assert all(scored.keyword_score == 0.0 for _, scored in without)


def test_dense_only_ablation_reproduces_the_week3_ranking(store):
    """
    With both stages off, search_hybrid must rank exactly as VectorStore.search
    does. That equivalence is what makes the baseline column in sections 9-14 the
    same retriever as the one behind sections 1-8.
    """
    for query in ("what is the late fee?", "AirFiber_1199_1M benefits", "mesh extender placement"):
        dense = [c.chunk_id for c, _ in store.search(query, top_k=5)]
        ablated = [
            c.chunk_id
            for c, _ in store.search_hybrid(
                query, top_k=5, candidate_k=len(store.chunks), rerank=False, use_keyword=False
            )
        ]
        assert dense == ablated, query


def test_ablation_flags_default_to_the_shipped_week4_behaviour(store):
    """
    `use_keyword` was added for the evaluation. Its default must leave the
    app's `week4` mode exactly as it was, or the ablation would have quietly
    changed the product it was meant to measure.
    """
    query = "what is error code AF-511"
    default = store.search_hybrid(query, top_k=5)
    explicit = store.search_hybrid(query, top_k=5, rerank=True, use_keyword=True)
    assert [c.chunk_id for c, _ in default] == [c.chunk_id for c, _ in explicit]


def test_results_md_carries_both_halves_of_the_report():
    """
    Two scripts write one file: evaluate_retrieval.py owns sections 1-8 and
    evaluate_week4.py owns 9-14 between the markers. Whichever ran last must not
    have deleted the other's half.
    """
    results = (Path(__file__).resolve().parents[2] / "results.md").read_text(encoding="utf-8")
    for heading in ("## 1. Chunking strategy comparison", "## 8. Final chunking decision"):
        assert heading in results
    assert "<!-- week4:start -->" in results and "<!-- week4:end -->" in results
    for heading in (
        "## 9. Week 4 golden set",
        "## 10. Baseline hit-rate@3",
        "## 11. Failure inspection and classification",
        "## 12. The one retrieval change",
        "## 13. Before -> after",
        "## 14. Shipping decision",
    ):
        assert heading in results, heading


def test_a_colloquial_but_answerable_question_falls_below_the_refusal_threshold(store, golden):
    """
    The one real defect the Week 4 golden set found, pinned so it cannot be
    "fixed" by accident and then quietly regress.

    W09's answer chunk is retrieved at rank 1, but its cosine is under
    SCORE_THRESHOLD, so `answer_with_groq` short-circuits and the user is told
    the documents do not cover a question the documents answer in full. This is
    the score-population overlap section 5 of results.md documents, arriving in
    practice. If someone changes the refusal design, this test should be updated
    deliberately - not deleted.
    """
    from app.services.rag_service import SCORE_THRESHOLD, answer_with_groq

    w09 = next(row for row in golden if row["id"] == "W09")
    results = store.search(w09["question"], top_k=3)
    retrieved = [f"{c.source}#{c.chunk_id}" for c, _ in results]

    # Retrieval succeeds - the labelled chunk is in the top 3.
    assert w09["expected_chunk_id"] in retrieved
    # ...and the gate refuses anyway, because it reads the best cosine in the set.
    assert results[0][1] < SCORE_THRESHOLD, (
        "W09 now scores above the threshold - the Gate finding in results.md section 11 is stale"
    )
    # client=None proves no LLM call is reached; the gate returns before using it.
    assert answer_with_groq(None, "unused-model", w09["question"], results) == (
        "I don't know. That isn't covered in the documents I have."
    )


def test_eval_only_temperature_does_not_change_the_app_request(monkeypatch):
    """
    `answer_with_groq` grew a `temperature` argument so the evaluation report is
    reproducible. The app must not pass it, and omitting it must not put
    `temperature` in the request at all - otherwise the harness would have
    changed the generation config it was meant to observe.
    """
    from app.services import rag_service as rag_module

    captured = {}

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "ok"})()})()]})()

    client = type("Client", (), {"chat": type("Chat", (), {"completions": _Completions()})()})()
    chunk = type("C", (), {"text": "body", "source": "s.md", "chunk_id": 0, "article_id": "", "section": ""})()

    rag_module.answer_with_groq(client, "m", "q", [(chunk, 0.9)])
    assert "temperature" not in captured

    captured.clear()
    rag_module.answer_with_groq(client, "m", "q", [(chunk, 0.9)], temperature=0.0)
    assert captured["temperature"] == 0.0


def test_the_contrast_questions_really_do_split_week3_from_week4(store):
    """
    G13 and G14 exist to demonstrate the mode toggle on a real case: Week 3
    retrieval misses the answer at k=3 and Week 4 recovers it. That claim is
    made in the UI, in the README, and in `golden_set.json`'s own notes, and
    nothing else checks it - if the corpus shifts and the split closes, the demo
    silently becomes a pair of questions both modes answer, and the notes become
    false. This test fails when that happens.
    """
    import json
    from pathlib import Path

    ui_set = json.loads(
        (Path(__file__).resolve().parents[1] / "eval" / "golden_set.json").read_text(encoding="utf-8")
    )
    contrast = [q for q in ui_set["questions"] if q.get("contrast") == "week3-miss-week4-hit"]
    assert len(contrast) == 2, "G13/G14 are the documented contrast pair"

    for q in contrast:
        needle = q["answer_contains"][0].lower()
        week3 = store.search(q["question"], top_k=3)
        week4 = store.search_hybrid(
            q["question"], top_k=3, candidate_k=len(store.chunks)
        )
        found3 = any(needle in c.text.lower() for c, _ in week3)
        found4 = any(needle in c.text.lower() for c, _ in week4)
        assert not found3, (
            f"{q['id']} no longer misses under Week 3 - the contrast has closed and the "
            f"note in golden_set.json is now wrong"
        )
        assert found4, f"{q['id']} is no longer recovered by Week 4"


def test_the_api_exposes_the_contrast_flag_the_ui_depends_on(golden):
    """
    `ChatInput.pickGolden` decides whether to scope retrieval to a document by
    reading `contrast` off the API payload. If the field stops being serialised
    the UI silently falls back to scoping, which removes the KB-007 competitors
    and makes G13/G14 answerable under Week 3 too - the demo would still look
    fine and prove nothing.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.rag_service import get_rag_service

    service = get_rag_service()
    service.reset_store()
    for path in sorted(SAMPLE_ROOT.rglob("*")):
        if path.suffix.lower() in {".md", ".txt"}:
            dest = service.docs_dir / path.relative_to(SAMPLE_ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())
    service.reindex()

    with TestClient(app) as client:
        rows = client.get("/api/golden-questions").json()["questions"]

    assert rows, "the golden set endpoint returned nothing"
    assert all("contrast" in row for row in rows)
    flagged = {row["id"] for row in rows if row["contrast"]}
    assert flagged == {"G13", "G14"}
    assert all(row["contrast"] == "week3-miss-week4-hit" for row in rows if row["contrast"])
