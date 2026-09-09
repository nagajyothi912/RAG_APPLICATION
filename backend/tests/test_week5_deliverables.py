"""
Tests for the Week 5 error-analysis deliverables.

Every one of these guards a claim the write-up makes that would otherwise rot
silently. A taxonomy citing a trace id that no longer exists still renders. An
open-coding sentence that smuggles in a fix still reads as a sentence. A sampler
whose seed no longer reproduces its own published draw still prints twenty ids.
The analysis is only worth what its provenance is worth, so the provenance is
pinned here.

Two of these read `git log`, because two rubric clauses - zero code changes
during open coding, and a prediction committed before any fix - are properties
of the history rather than of any file.
"""

import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
WEEK5 = ROOT / "docs" / "week5"

BANK = BACKEND / "eval" / "week5" / "ticket_bank.jsonl"
TRACES = WEEK5 / "traces.jsonl"
SAMPLE = WEEK5 / "sample.json"
TAXONOMY = WEEK5 / "taxonomy.md"
NOTES = WEEK5 / "notes.md"
PREDICTION = WEEK5 / "prediction.md"

SEVERITIES = {"embarrasses the client", "annoys the user"}

# Names that describe a diagnosis or a component rather than what a reader would
# see. "retrieval issue" tells a manager nothing about what to do.
BANNED_MODE_WORDS = [
    "retrieval issue", "retrieval problem", "chunking problem", "chunking issue",
    "hallucination", "bad answer", "wrong answer", "context issue", "llm error",
    "embedding problem", "prompt issue", "quality issue",
]

# Vocabulary that turns an observation into a recommendation. Open coding is
# meant to record what happened; the diagnosis is next week's job.
FIX_WORDS = [
    "we should", "should be", "we could", "we need to", "recommend", "the fix",
    "to fix", "instead we", "increase top_k", "lower the threshold",
    "raise the threshold", "i would", "needs to be changed",
]

requires_git = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(),
    reason="not a git checkout",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def bank() -> list[dict]:
    return [row for row in _jsonl(BANK) if "_bank" not in row]


@pytest.fixture(scope="module")
def traces() -> list[dict]:
    return _jsonl(TRACES)


@pytest.fixture(scope="module")
def sample() -> dict:
    return json.loads(SAMPLE.read_text("utf-8"))


@pytest.fixture(scope="module")
def taxonomy_rows() -> list[dict]:
    """Rows of the one table in taxonomy.md whose first cell is an integer."""
    rows = []
    for line in TAXONOMY.read_text("utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        rows.append(
            {
                "n": int(cells[0]),
                "mode": cells[1],
                "count": int(cells[2]),
                "pct": cells[3],
                "severity": cells[4],
                "example": cells[5].strip("`"),
            }
        )
    return rows


# --------------------------------------------------------------------- bank

def test_the_ticket_bank_holds_one_hundred_and_twenty_unique_questions(bank):
    assert len(bank) == 120
    assert len({row["question"].strip().lower() for row in bank}) == 120
    assert [row["ticket_id"] for row in bank] == [f"T{i:03d}" for i in range(1, 121)]


def test_no_ticket_carries_an_expected_answer_or_a_failure_label(bank):
    """
    The anti-pre-decision guard. The moment an entry says which chunk is
    correct, or which bucket it came from, open coding stops being observation
    and becomes grading against a label written before anyone looked - which is
    the assignment's number-one listed mistake. This test is what stops the
    fixture quietly acquiring an expected_chunk_id in six months.
    """
    allowed = {"ticket_id", "question", "channel", "authored_on"}
    for row in bank:
        assert set(row) <= allowed | {"retired"}, row["ticket_id"]


def test_the_ticket_bank_is_disjoint_from_every_existing_eval_fixture(bank):
    """
    Reusing a gold question would import its label by the back door and would
    also let a Week 5 edit move a number in results.md.
    """
    existing = set()
    gold = json.loads((BACKEND / "eval" / "gold_questions.json").read_text("utf-8"))
    for value in gold.values():
        if isinstance(value, list):
            existing |= {q["question"].strip().lower() for q in value}
    existing |= {
        q["question"].strip().lower()
        for q in json.loads((BACKEND / "eval" / "golden_set.json").read_text("utf-8"))["questions"]
    }
    existing |= {r["question"].strip().lower() for r in _jsonl(BACKEND / "eval" / "golden_set.jsonl")}
    assert {row["question"].strip().lower() for row in bank} & existing == set()


@requires_git
def test_the_ticket_bank_was_committed_before_any_tracing_code_existed():
    """
    "Authored blind" has to be checkable, not asserted. At the commit that added
    the bank, the app could not produce a trace at all.
    """
    bank_commit = _git("log", "--format=%ct", "-1", "--", str(BANK.relative_to(ROOT)))
    trace_code = _git(
        "log", "--format=%ct", "--reverse", "--", "backend/app/services/tracing.py"
    ).splitlines()
    assert bank_commit and trace_code, "expected both paths to be committed"
    assert int(bank_commit) <= int(trace_code[0])


# ------------------------------------------------------------------- traces

def test_every_ticket_and_every_demo_question_produced_a_trace(bank, traces):
    """A dropped trace biases the sample, so absence must be loud."""
    random_ids = {t["source_id"] for t in traces if t.get("pool") == "random"}
    assert random_ids == {row["ticket_id"] for row in bank}
    demo = json.loads((BACKEND / "eval" / "golden_set.json").read_text("utf-8"))["questions"]
    assert {t["source_id"] for t in traces if t.get("pool") == "demo"} == {q["id"] for q in demo}


def test_trace_ids_are_unique_and_their_prefix_matches_their_pool(traces):
    """
    A bare trace id pasted into the taxonomy has to be self-identifying about
    which pool it came from, or a reader cannot tell a random-sample example
    from a curated demo one.
    """
    assert len({t["trace_id"] for t in traces}) == len(traces)
    prefixes = {"random": "TR-", "demo": "TD-", "demo_unscoped": "TU-"}
    for trace in traces:
        assert trace["trace_id"].startswith(prefixes[trace["pool"]]), trace["trace_id"]


def test_every_trace_records_the_configuration_needed_to_replay_it(traces):
    for trace in traces:
        config = trace["config"]
        assert (config["chunk_strategy"], config["chunk_size"], config["chunk_overlap"]) == (
            "heading", 1000, 100,
        )
        assert config["embed_model"] == "all-MiniLM-L6-v2"
        assert config["corpus"]["fingerprint"]
        assert trace["generation"]["prompt_id"]


def test_every_generated_trace_pinned_the_temperature_so_it_can_be_replayed(traces):
    """
    The shipped app leaves temperature unset, so Groq uses its own default and
    the same prompt returns differently worded text on every call. The
    collection run pins it to 0; without that the replay deliverable is not
    possible at all.
    """
    called = [t for t in traces if t["generation"]["called"]]
    assert called, "no trace reached the model"
    for trace in called:
        assert trace["generation"]["params"]["temperature"] == 0.0, trace["trace_id"]


def test_every_cited_chunk_resolves_at_the_recorded_chunk_configuration(traces):
    """
    Chunk ids are positional and only valid at heading/1000/100. A rechunk
    renumbers everything and would silently orphan every id in the write-up.
    """
    import sys

    sys.path.insert(0, str(BACKEND))
    from app.services.rag_service import build_chunks

    chunks = build_chunks(str(ROOT / "sample_documents"), chunk_size=1000, overlap=100, strategy="heading")
    known = {f"{c.source}#{c.chunk_id}" for c in chunks}
    for trace in traces:
        for chunk in trace["retrieval"]["chunks"]:
            assert chunk["chunk_uid"] in known, f"{trace['trace_id']}: {chunk['chunk_uid']}"


def test_the_traffic_is_weighted_to_the_shipped_defaults(traces):
    """Keeps the sentence describing the traffic mix in notes.md honest."""
    pool = [t for t in traces if t["pool"] == "random"]
    n = len(pool)
    assert sum(t["request"]["mode_effective"] == "week4" for t in pool) / n >= 0.6
    assert sum(t["request"]["top_k_effective"] == 5 for t in pool) / n >= 0.6
    assert sum(not t["request"]["filters"] for t in pool) / n >= 0.6


def test_the_demo_traces_reproduce_the_uis_golden_question_scoping(traces):
    """
    The demo pool only means something if it was run the way it is demoed.
    pickGolden scopes each question to its own document and clears the scope for
    the two contrast questions, whose whole point is the whole corpus.
    """
    demo = {
        q["id"]: q
        for q in json.loads((BACKEND / "eval" / "golden_set.json").read_text("utf-8"))["questions"]
    }
    for trace in traces:
        if trace["pool"] != "demo":
            continue
        scoped = bool(trace["request"]["filters"].get("source"))
        assert scoped is not bool(demo[trace["source_id"]].get("contrast")), trace["source_id"]


# ------------------------------------------------------------------ sampler

def test_the_sampler_is_reproducible_under_its_own_published_seed(sample, traces):
    """
    The published seed and algorithm have to actually reproduce the published
    draw, or the "provably random" claim is decorative.
    """
    import random

    for pool, key in (("random", "random"), ("demo", "demo")):
        ids = sorted(t["trace_id"] for t in traces if t["pool"] == pool)
        rng = random.Random(f"{sample['seed']}:{pool}")
        assert sorted(rng.sample(ids, len(sample[key]))) == sample[key]


def test_the_two_pools_are_drawn_from_independent_streams(sample, traces):
    """
    With one shared stream, adding the bonus draw would silently move the
    twenty already quoted in the taxonomy.
    """
    import random

    ids = sorted(t["trace_id"] for t in traces if t["pool"] == "random")
    rng = random.Random(f"{sample['seed']}:random")
    first = sorted(rng.sample(ids, len(sample["random"])))
    rng2 = random.Random(f"{sample['seed']}:demo")
    rng2.sample(sorted(t["trace_id"] for t in traces if t["pool"] == "demo"), 3)
    assert first == sample["random"]


def test_the_sample_is_pinned_to_the_trace_file_it_was_drawn_from(sample):
    assert hashlib.sha256(TRACES.read_bytes()).hexdigest() == sample["traces_sha256"]


def test_the_sampled_traces_all_come_from_the_pool_they_claim(sample, traces):
    pools = {t["trace_id"]: t["pool"] for t in traces}
    assert {pools[i] for i in sample["random"]} == {"random"}
    assert {pools[i] for i in sample["demo"]} == {"demo"}
    assert len(sample["random"]) == 20 and len(sample["demo"]) == 10


# ----------------------------------------------------------------- taxonomy

def test_the_taxonomy_names_between_four_and_seven_failure_modes(taxonomy_rows):
    assert 4 <= len(taxonomy_rows) <= 7


def test_the_taxonomy_counts_account_for_all_twenty_sampled_traces(taxonomy_rows):
    text = TAXONOMY.read_text("utf-8")
    residual = re.search(r"^\|\s*—\s*\|[^|]*\|\s*(\d+)\s*\|", text, re.M)
    total = sum(row["count"] for row in taxonomy_rows) + (int(residual.group(1)) if residual else 0)
    assert total == 20, f"modes plus residual came to {total}"


def test_every_taxonomy_percentage_matches_its_count(taxonomy_rows):
    for row in taxonomy_rows:
        assert float(row["pct"].rstrip("%")) == row["count"] * 5, row["mode"]


def test_every_taxonomy_severity_is_one_of_the_two_allowed_phrases(taxonomy_rows):
    for row in taxonomy_rows:
        assert row["severity"] in SEVERITIES, row["severity"]


def test_every_taxonomy_example_was_one_of_the_sampled_twenty(taxonomy_rows, sample):
    for row in taxonomy_rows:
        assert row["example"] in sample["random"], row["example"]


def test_the_taxonomy_fits_on_one_screen():
    lines = TAXONOMY.read_text("utf-8").splitlines()
    assert len(lines) <= 45, f"{len(lines)} lines"


def test_no_mode_name_is_a_generic_retrieval_word(taxonomy_rows):
    """
    "retrieval issue" is a diagnosis smuggled in as an observation, and it tells
    a manager nothing about what to do. Names have to be legible to a stranger.
    """
    for row in taxonomy_rows:
        lowered = row["mode"].lower()
        for banned in BANNED_MODE_WORDS:
            assert banned not in lowered, f"{row['mode']!r} contains {banned!r}"
        assert len(row["mode"].split()) >= 4, f"{row['mode']!r} is too short to be legible"


# -------------------------------------------------------------------- notes

def _open_coding_lines() -> list[str]:
    text = NOTES.read_text("utf-8")
    body = text.split("## 3. Open coding")[1].split("## 4.")[0]
    return [
        line.strip()
        for line in body.splitlines()
        if re.match(r"^\d+\.\s+`T", line.strip())
    ]


def test_the_notes_contain_exactly_twenty_open_coding_sentences():
    assert len(_open_coding_lines()) == 20


def test_every_open_coding_line_names_a_trace_from_the_sampled_twenty(sample):
    cited = [re.search(r"`(TR-\d+)`", line).group(1) for line in _open_coding_lines()]
    assert sorted(cited) == sorted(sample["random"])


def test_open_coding_sentences_name_no_mode_and_propose_no_fix(taxonomy_rows):
    """
    The 25-mark clause: one sentence describing what was SEEN, not the category
    and not the fix. A sentence that names its own mode is a category, and a
    sentence saying what to change is next week's job done early.
    """
    modes = {row["mode"].lower() for row in taxonomy_rows}
    for line in _open_coding_lines():
        lowered = line.lower()
        for mode in modes:
            assert mode not in lowered, f"names its own mode: {line[:80]}"
        for word in FIX_WORDS:
            assert word not in lowered, f"proposes a fix ({word!r}): {line[:80]}"


@pytest.mark.parametrize(
    "heading",
    [
        "## 0. What was run, and against what",
        "## 1. The seeded sample",
        "## 2. Replay of one trace, from the trace alone",
        "### 2.3 Fields I had to add",
        "### 2.4 What I could not reconstruct",
        "## 3. Open coding",
        "### 3.1 Zero code changes during this step",
        "## 4. Clustering into failure modes",
        "## 5. The prediction",
        "## 6. Why a public benchmark would not have surfaced the top three",
        "## 7. Bonus",
    ],
)
def test_the_notes_carry_every_graded_artifact(heading):
    """
    Each is a separate rubric line item. Losing one is silent otherwise: the
    document still renders and still looks complete.
    """
    assert heading in NOTES.read_text("utf-8"), heading


def test_the_benchmark_note_is_exactly_three_sentences():
    text = NOTES.read_text("utf-8")
    body = text.split("## 6. Why a public benchmark would not have surfaced the top three")[1]
    body = body.split("## 7.")[0]
    # Drop the markdown horizontal rule that separates the sections.
    body = "\n".join(line for line in body.splitlines() if line.strip() != "---").strip()
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
    assert len(sentences) == 3, f"found {len(sentences)}"


# --------------------------------------------------------------- prediction

def test_the_prediction_is_dated_and_names_a_mode_a_change_and_numbers(taxonomy_rows):
    text = PREDICTION.read_text("utf-8")
    assert "2026-09-07" in text
    assert any(row["mode"].lower() in text.lower() for row in taxonomy_rows)
    assert len(re.findall(r"\d+\s*/\s*20", text)) >= 2, "needs at least two n/20 figures"
    assert re.search(r"[-+−]\s?\d+(\.\d+)?\s*(points|pp|percentage points)", text, re.I)
    assert "falsified if" in text.lower()


@requires_git
def test_the_prediction_commit_touched_only_the_prediction_file():
    """
    The prediction lives alone so its hash is final the moment it lands, and a
    later commit can paste that hash into the notes without circularity.
    """
    commit = _git("log", "--format=%H", "-1", "--diff-filter=A", "--", "docs/week5/prediction.md")
    assert commit, "prediction.md has no adding commit"
    files = _git("show", "--name-only", "--format=", commit).split()
    assert files == ["docs/week5/prediction.md"], files


@requires_git
def test_the_notes_quote_the_real_hash_of_the_prediction_commit():
    commit = _git("log", "--format=%H", "-1", "--diff-filter=A", "--", "docs/week5/prediction.md")
    assert commit[:7] in NOTES.read_text("utf-8"), "notes do not quote the prediction commit"


@requires_git
def test_no_source_file_changed_during_the_open_coding_commit():
    """
    "Zero code changes during this step" is a property of the history. The
    open-coding commit must touch exactly one file, and it must not be code.
    """
    commit = _git("log", "--format=%H", "--grep=^week5: open coding", "-1")
    assert commit, "no open-coding commit found"
    files = _git("show", "--name-only", "--format=", commit).split()
    assert files == ["docs/week5/notes.md"], files


def _function_source(text: str, name: str) -> str:
    """The source of one top-level or method-level def, located by AST."""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            lines = text.splitlines()[node.lineno - 1 : node.end_lineno]
            return "\n".join(lines)
    raise AssertionError(f"{name} not found")


# The surfaces that decide what a user is shown: retrieval, the refusal gate,
# the prompt, and the generation call. A change to any of these after the
# prediction is a fix; a change anywhere else is not.
BEHAVIOURAL_FILES = [
    "backend/app/services/retrieval.py",
    "backend/app/services/chunking.py",
]
BEHAVIOURAL_FUNCTIONS = [
    ("backend/app/services/rag_service.py", "retrieve"),
    ("backend/app/services/rag_service.py", "answer_with_groq"),
    ("backend/app/services/rag_service.py", "_ask_inner"),
]


@requires_git
def test_nothing_was_fixed_after_the_prediction_was_committed():
    """
    The 15-mark clause is "committed before any fix".

    This deliberately does NOT assert that no file under backend/app changed.
    That proxy is too coarse: adding a telemetry sink changes files there while
    changing nothing a user is shown, and a test that cannot tell those apart
    either blocks observability work or gets weakened until it means nothing.

    What it asserts instead is that the code deciding what the user sees is
    byte-identical to the prediction commit - retrieval, chunking, the refusal
    gate, the prompt, and the generation call. Retuning SCORE_THRESHOLD, gating
    on the rerank score, or editing the system prompt all land here and all fail.
    """
    commit = _git("log", "--format=%H", "-1", "--diff-filter=A", "--", "docs/week5/prediction.md")
    assert commit, "prediction.md has no adding commit"

    for path in BEHAVIOURAL_FILES:
        then = _git("show", f"{commit}:{path}")
        now = (ROOT / path).read_text(encoding="utf-8")
        assert then.strip() == now.strip(), f"{path} changed after the prediction"

    for path, func in BEHAVIOURAL_FUNCTIONS:
        then = _function_source(_git("show", f"{commit}:{path}"), func)
        now = _function_source((ROOT / path).read_text(encoding="utf-8"), func)
        assert then == now, f"{func}() in {path} changed after the prediction"


@requires_git
def test_the_refusal_threshold_has_not_moved_since_the_prediction():
    """
    The prediction names retuning SCORE_THRESHOLD as the thing it will NOT do,
    because results.md section 5 documents that as the mistake the evaluation
    exists to prevent. Worth pinning on its own, since it is one character to
    change and would invalidate every frequency in the taxonomy.
    """
    import sys

    sys.path.insert(0, str(BACKEND))
    from app.services.rag_service import SCORE_THRESHOLD

    assert SCORE_THRESHOLD == 0.15
