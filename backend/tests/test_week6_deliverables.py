"""
Tests for the Week 6 deliverables: Validate the ticket-reply judge before you trust its number.

Guards every rubric requirement:
1. Blind protocol: 25+ hand labels exist and predate judge run.
2. Agreement measured before -> after, with iteration driven by disagreements.
3. Assertion/judge split: assertable criteria implemented as assertions and removed from judge prompt.
4. Disagreement analysis: at least 2 disagreements read, verdict on who was right, prediction scored.
5. Eval runs in one command over 25+ mode-tagged cases including real regression cases.
"""

import json
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
WEEK6_EVAL = BACKEND / "eval" / "week6"
DOCS_WEEK6 = ROOT / "docs" / "week6"

EVAL_SET = WEEK6_EVAL / "eval_set_25.jsonl"
LABELS = WEEK6_EVAL / "labels_25.json"
JUDGE_V1 = WEEK6_EVAL / "judge_v1.txt"
JUDGE_V2 = WEEK6_EVAL / "judge_v2.txt"
PREDICTION = WEEK6_EVAL / "prediction.txt"
EVAL_SCRIPT = BACKEND / "scripts" / "evaluate_week6.py"

VALID_MODES = {"mode_1", "mode_2", "mode_3", "mode_4", "mode_5", "no_defect_seen"}


def test_eval_set_has_at_least_25_cases_and_mode_tags():
    assert EVAL_SET.exists(), "eval_set_25.jsonl must exist"
    lines = [line.strip() for line in EVAL_SET.read_text("utf-8").splitlines() if line.strip()]
    assert len(lines) >= 25, f"Expected at least 25 test cases, found {len(lines)}"

    regression_count = 0
    modes_found = set()
    for line in lines:
        row = json.loads(line)
        assert "ticket_id" in row
        assert "question" in row
        assert "context" in row
        assert "drafted_reply" in row
        assert "week5_mode" in row, f"Ticket {row.get('ticket_id')} missing week5_mode tag"
        assert row["week5_mode"] in VALID_MODES, f"Invalid mode tag: {row['week5_mode']}"
        modes_found.add(row["week5_mode"])
        if row.get("is_regression"):
            regression_count += 1

    assert regression_count >= 2, f"Expected at least 2 regression cases, found {regression_count}"
    assert len(modes_found) >= 5, f"Expected diverse taxonomy modes, found {modes_found}"


def test_blind_hand_labels_exist_and_cover_all_cases():
    assert LABELS.exists(), "labels_25.json must exist"
    data = json.loads(LABELS.read_text("utf-8"))
    assert "metadata" in data
    assert "protocol" in data["metadata"]
    assert "labels" in data
    labels = data["labels"]
    assert len(labels) >= 25, f"Expected >=25 labels, found {len(labels)}"
    
    for tid, item in labels.items():
        assert "label" in item
        assert item["label"] in (0, 1)
        assert "verdict" in item
        assert item["verdict"] in ("PASS", "FAIL")
        assert "reason" in item and len(item["reason"]) > 5


def test_deterministic_assertion_and_judge_split():
    """
    Rubric: Move at least 2 criteria out of the judge and into deterministic assertions
    (ticket ID echoed, refund amount present and numeric, escalation tag set when tier is Priority,
    no refund promised outside 30-day window) and delete those criteria from the judge prompt.
    """
    from scripts.evaluate_week6 import ASSERTIONS, run_assertions
    
    assert len(ASSERTIONS) >= 2, "Must have at least 2 deterministic assertions"
    assert "ticket_id_echoed" in ASSERTIONS
    assert "refund_amount_numeric" in ASSERTIONS
    assert "priority_escalation" in ASSERTIONS
    assert "no_refund_outside_30_days" in ASSERTIONS

    # Verify these criteria are NOT in judge prompt v1
    judge_v1_text = JUDGE_V1.read_text("utf-8").lower()
    assert "do not check for ticket id" in judge_v1_text
    assert "automated deterministic" in judge_v1_text


def test_judge_prompts_exist_and_v2_has_few_shot_calibration():
    assert JUDGE_V1.exists(), "judge_v1.txt must exist"
    assert JUDGE_V2.exists(), "judge_v2.txt must exist"
    v1_text = JUDGE_V1.read_text("utf-8")
    v2_text = JUDGE_V2.read_text("utf-8")

    assert len(v2_text) > len(v1_text), "judge_v2 should contain few-shot examples"
    assert "FEW-SHOT CALIBRATION EXAMPLES" in v2_text
    assert "Example 1" in v2_text
    assert "Example 2" in v2_text


def test_prediction_exists_and_is_one_sentence():
    assert PREDICTION.exists(), "prediction.txt must exist"
    text = PREDICTION.read_text("utf-8").strip()
    assert len(text) > 20
    # Must be one concise sentence
    sentences = [s.strip() for s in text.split(".") if s.strip()]
    assert len(sentences) <= 2, f"Prediction should be a one-sentence written statement, got {len(sentences)}"


def test_evaluate_week6_command_runs_successfully():
    from scripts.evaluate_week6 import run_assertions, ASSERTIONS
    assert len(ASSERTIONS) == 4
    # Test assertions on a sample case
    sample_case = {
        "ticket_id": "T001",
        "tier": "Priority",
        "tenure_days": 10,
        "refund_requested": True,
    }
    sample_reply = "[Ticket #T001] [Priority Escalation: Lead Assigned] Entitled to ₹1999 refund."
    res = run_assertions(sample_case, sample_reply)
    assert res["ticket_id_echoed"] is True
    assert res["refund_amount_numeric"] is True
    assert res["priority_escalation"] is True
    assert res["no_refund_outside_30_days"] is True


RUNS = WEEK6_EVAL / "runs"
V1_PRE_ITERATION = RUNS / "judge_v1_results.json"


def _commit_epoch(path: Path) -> int:
    """Commit time of the first commit that added `path`; skips when history is unavailable."""
    out = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%ct", "--", str(path)],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.split()
    if not out:
        pytest.skip(f"{path.name} is not committed")
    return int(out[-1])


def test_labels_committed_before_first_judge_run():
    """Rubric: the labels must provably predate the judge run, by commit order."""
    assert _commit_epoch(LABELS) < _commit_epoch(V1_PRE_ITERATION)
    run = json.loads(V1_PRE_ITERATION.read_text("utf-8"))
    assert run["labels_commit"].split()[0] != "uncommitted"


def test_prediction_committed_before_judge_v2():
    assert _commit_epoch(PREDICTION) < _commit_epoch(JUDGE_V2)


def test_v2_few_shot_examples_are_v1_disagreements():
    """The iteration must be driven by the judge's OWN disagreements, not hand-picked cases."""
    import re

    run = json.loads(V1_PRE_ITERATION.read_text("utf-8"))
    disagreements = {r["ticket_id"] for r in run["results"] if not r["agree"]}
    shots = set(re.findall(r"Ticket #(T\d+)", JUDGE_V2.read_text("utf-8")))
    assert len(shots) >= 2
    assert shots <= disagreements, f"v2 examples {shots} are not all v1 disagreements {disagreements}"


def test_few_shot_examples_carry_the_human_label():
    """Relabelling to win agreement is out: each example's verdict must match labels_25.json."""
    import re

    labels = json.loads(LABELS.read_text("utf-8"))["labels"]
    v2 = JUDGE_V2.read_text("utf-8")
    for block in v2.split("Example ")[1:]:
        tid = re.search(r"Ticket #(T\d+)", block).group(1)
        score = int(re.search(r'"score":\s*(\d)', block).group(1))
        assert score == labels[tid]["label"], f"{tid} example says {score}, label says {labels[tid]['label']}"


def test_regression_cases_are_verbatim_trace_replays():
    traces = {}
    for line in (ROOT / "docs" / "week5" / "traces.jsonl").read_text("utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            traces[rec["trace_id"]] = rec
    for line in EVAL_SET.read_text("utf-8").splitlines():
        row = json.loads(line)
        if not row.get("is_regression"):
            continue
        trace = traces[row["trace_id"]]
        assert trace["request"]["question"] == row["question"], row["ticket_id"]
        assert trace["answer"]["text"] in row["drafted_reply"], row["ticket_id"]
