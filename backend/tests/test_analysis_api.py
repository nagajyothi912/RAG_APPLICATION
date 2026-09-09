"""
Tests for the read-only routes behind the Error Analysis tab.

The point of these is that the UI and the write-up cannot drift apart. The
taxonomy is parsed out of taxonomy.md rather than duplicated in code, and the
open coding out of notes.md, so a change to either file must show up here - and
if the parsing silently stops matching, the tab would render an empty table
rather than a wrong one, which is exactly the kind of failure a human does not
notice.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import analysis_store as store

ROOT = Path(__file__).resolve().parents[2]
WEEK5 = ROOT / "docs" / "week5"

pytestmark = pytest.mark.skipif(
    not (WEEK5 / "traces.jsonl").exists(),
    reason="the Week 5 artifacts are not present in this checkout",
)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def fresh_cache():
    store.reset_cache()
    yield
    store.reset_cache()


def test_the_summary_counts_every_trace_in_the_committed_run(client):
    body = client.get("/api/analysis/summary").json()
    assert body["available"] is True
    assert body["traces"] == sum(body["pools"].values())
    assert body["pools"]["random"] == 120
    assert sum(body["statuses"].values()) == body["traces"]


def test_the_summary_taxonomy_matches_taxonomy_md(client):
    """
    The tab renders the same modes the rubric is graded on. A second copy in
    code would drift, so this asserts the parse still finds all of them.
    """
    body = client.get("/api/analysis/summary").json()
    assert 4 <= len(body["modes"]) <= 7
    counted = sum(m["count"] for m in body["modes"]) + body["residual"]["count"]
    assert counted == body["sample_size"] == 20
    for mode in body["modes"]:
        assert mode["percent"] == mode["count"] * 5
        assert mode["severity"] in {"embarrasses the client", "annoys the user"}
        assert mode["example_trace_id"].startswith("TR-")


def test_the_summary_reports_the_published_seed_and_the_sampled_ids(client):
    body = client.get("/api/analysis/summary").json()
    sample = json.loads((WEEK5 / "sample.json").read_text("utf-8"))
    assert body["sample_seed"] == sample["seed"]
    assert body["sampled_random"] == sample["random"]
    assert len(body["sampled_random"]) == 20
    assert body["coded"] == 30


def test_the_trace_list_paginates_and_reports_the_unfiltered_total(client):
    body = client.get("/api/analysis/traces", params={"limit": 10}).json()
    assert body["total"] == 148
    assert len(body["rows"]) == 10
    second = client.get("/api/analysis/traces", params={"limit": 10, "offset": 10}).json()
    assert {r["trace_id"] for r in body["rows"]} & {r["trace_id"] for r in second["rows"]} == set()


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"pool": "random"}, 120),
        ({"pool": "demo"}, 14),
        ({"sampled": "random"}, 20),
        ({"sampled": "demo"}, 10),
        ({"sampled": "any"}, 30),
        ({"status": "refused"}, 12),
        ({"refused": "true"}, 12),
        ({"failure_mode": "any"}, 20),
    ],
)
def test_the_filters_return_the_counts_the_write_up_claims(client, params, expected):
    """Each of these numbers is quoted in taxonomy.md or notes.md."""
    body = client.get("/api/analysis/traces", params={**params, "limit": 1}).json()
    assert body["total"] == expected


def test_filtering_by_a_failure_mode_returns_exactly_its_taxonomy_count(client):
    summary = client.get("/api/analysis/summary").json()
    for mode in summary["modes"]:
        body = client.get(
            "/api/analysis/traces", params={"failure_mode": mode["name"], "limit": 1}
        ).json()
        assert body["total"] == mode["count"], mode["name"]


def test_a_sampled_trace_carries_the_open_coding_sentence_written_about_it(client):
    """
    The sentence sitting next to the retrieval it describes is the whole reason
    this tab beats reading the markdown.
    """
    body = client.get("/api/analysis/traces/TR-0055").json()
    assert body["sampled"] == "random"
    assert body["open_coding"].startswith("The follow-up")
    assert body["failure_mode"] == "Refuses while the chunk that answers it is ranked first"


def test_a_gate_refusal_detail_shows_that_the_model_was_never_called(client):
    """
    The distinction the schema exists to preserve: the user saw a refusal string
    we wrote, not one the model produced.
    """
    trace = client.get("/api/analysis/traces/TR-0055").json()["trace"]
    assert trace["generation"]["called"] is False
    assert trace["generation"]["system_prompt"] is None
    assert trace["answer"]["source"] == "gate_refusal"
    assert trace["retrieval"]["gate_score"] < trace["retrieval"]["score_threshold"]


def test_an_answered_trace_detail_carries_the_prompt_and_the_raw_output(client):
    trace = client.get("/api/analysis/traces/TR-0098").json()["trace"]
    assert trace["generation"]["called"] is True
    assert trace["generation"]["user_prompt"]
    assert trace["generation"]["raw_output"]
    assert trace["retrieval"]["chunks"][0]["rank"] == 1


def test_search_matches_the_question_text(client):
    body = client.get("/api/analysis/traces", params={"q": "mesh extender"}).json()
    assert body["total"] >= 1
    assert all("mesh extender" in r["question"].lower() or "mesh extender" in r["answer_preview"].lower()
               for r in body["rows"])


def test_an_unknown_trace_id_is_a_404_not_an_empty_result(client):
    assert client.get("/api/analysis/traces/TR-9999").status_code == 404


def test_an_unknown_source_is_rejected(client):
    assert client.get("/api/analysis/summary", params={"source": "../etc"}).status_code == 400


def test_the_live_source_is_served_separately_from_the_analysed_run(client, tmp_path, monkeypatch):
    """
    Pointing the tab at the live file must not silently show the committed run,
    or someone debugging a fresh failure would be reading week-old traces.
    """
    live = tmp_path / "live.jsonl"
    live.write_text("", encoding="utf-8")
    monkeypatch.setattr(store.settings, "trace_path", live)
    store.reset_cache()
    body = client.get("/api/analysis/summary", params={"source": "live"}).json()
    assert body["available"] is False
    assert body["traces"] == 0
