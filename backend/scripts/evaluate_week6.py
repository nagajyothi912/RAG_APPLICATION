#!/usr/bin/env python3
"""
Week 6 Evaluation Runner — Validate the ticket-reply judge before you trust its number.

Features:
1. Loads 26+ mode-tagged support ticket cases across all Week 5 taxonomy modes.
2. Runs 4 deterministic assertions (ticket ID, numeric refund amount, priority escalation, 30-day refund window).
3. Compares LLM Judge v1 (zero-shot) and LLM Judge v2 (few-shot calibrated) against ground truth human labels.
4. Computes agreement_before -> agreement_after and breakdown by Week 5 taxonomy mode.
5. Emits traces and scores directly to Langfuse (https://us.cloud.langfuse.com/project/cmts8l4k00513ad0g86x36tlp).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

EVAL_DIR = BACKEND / "eval" / "week6"
EVAL_SET = EVAL_DIR / "eval_set_25.jsonl"
LABELS_FILE = EVAL_DIR / "labels_25.json"
JUDGE_V1_PROMPT = EVAL_DIR / "judge_v1.txt"
JUDGE_V2_PROMPT = EVAL_DIR / "judge_v2.txt"
PREDICTION_FILE = EVAL_DIR / "prediction.txt"
RUNS_DIR = EVAL_DIR / "runs"

# The only criterion left for the LLM once the four assertions below took the rest.
JUDGED_CRITERIA = 1

os.environ.setdefault("LANGFUSE_ENABLED", "true")

from app.config import settings
from app.services import langfuse_sink
from openai import OpenAI


# ==============================================================================
# Deterministic Assertions (Moved out of LLM Judge)
# ==============================================================================

def assert_ticket_id_echoed(case: dict, reply: str) -> bool:
    """Verifies that the ticket ID (e.g., T001, T012) is echoed in the reply."""
    tid = case.get("ticket_id", "")
    if not tid:
        return True
    return bool(re.search(rf"\b{re.escape(tid)}\b", reply, re.IGNORECASE))


def assert_refund_amount_numeric(case: dict, reply: str) -> bool:
    """
    If a refund is discussed or promised, asserts that the amount is explicitly stated and numeric.
    """
    if "refund" in reply.lower() and ("eligible for" in reply.lower() or "entitled to" in reply.lower() or "processed" in reply.lower() or "refund of" in reply.lower()):
        # Must contain ₹ followed by digits or numeric figure
        return bool(re.search(r"₹\s*\d+", reply) or re.search(r"\b\d+\s*(rupees|rs|inr)\b", reply, re.IGNORECASE))
    return True


def assert_priority_escalation(case: dict, reply: str) -> bool:
    """
    If customer tier is Priority, asserts that priority escalation path/tag is set.
    """
    if case.get("tier") == "Priority":
        escalation_markers = ["priority", "escalat", "supervisor", "ops lead", "senior", "lead assigned"]
        return any(m in reply.lower() for m in escalation_markers)
    return True


def assert_no_refund_outside_30_days(case: dict, reply: str) -> bool:
    """
    Asserts that no full refund is promised outside the 30-day activation window.
    """
    tenure = case.get("tenure_days", 0)
    refund_requested = case.get("refund_requested", False)
    if tenure > 30 and refund_requested:
        # Should NOT promise a full refund of plan charges; must state cannot issue full refund or provide downtime credit
        lower_reply = reply.lower()
        if "100% refund" in lower_reply or "full refund of" in lower_reply:
            return False
    return True


ASSERTIONS = {
    "ticket_id_echoed": assert_ticket_id_echoed,
    "refund_amount_numeric": assert_refund_amount_numeric,
    "priority_escalation": assert_priority_escalation,
    "no_refund_outside_30_days": assert_no_refund_outside_30_days,
}


def run_assertions(case: dict, reply: str) -> Dict[str, bool]:
    return {name: fn(case, reply) for name, fn in ASSERTIONS.items()}


# ==============================================================================
# LLM Judge Execution
# ==============================================================================

def judge_user_prompt(case: dict) -> str:
    return f"""Context:
{case.get('context', '')}

Customer Question:
{case.get('question', '')}

Drafted Ticket Reply:
{case.get('drafted_reply', '')}
"""


def call_llm_judge(client: OpenAI, system_prompt: str, case: dict, model: str) -> Dict[str, Any]:
    """
    Invokes the LLM judge on a single case.

    A reply the judge could not score comes back with `error` set rather than as a
    silent FAIL: counting a parse failure as score 0 would quietly move agreement on
    every case the human labelled FAIL.
    """
    user_prompt = judge_user_prompt(case)
    last_error = ""
    for _attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"} if "openai" in model or "compound" in model else None,
            )
            content = response.choices[0].message.content or "{}"
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                score = int(parsed.get("score", 0))
                explanation = parsed.get("explanation", "")
                usage = getattr(response, "usage", None)
                return {
                    "score": 1 if score > 0 else 0, "explanation": explanation, "raw": content, "error": False,
                    "model": getattr(response, "model", None) or model,
                    "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                    "usage": {
                        k: v for k, v in {
                            "input": getattr(usage, "prompt_tokens", None),
                            "output": getattr(usage, "completion_tokens", None),
                            "total": getattr(usage, "total_tokens", None),
                        }.items() if isinstance(v, int)
                    },
                }
            last_error = f"no JSON object in judge output: {content[:120]!r}"
        except Exception as exc:
            last_error = str(exc)
    print(f"    [Judge Error on {case.get('ticket_id')}]: {last_error}")
    return {"score": 0, "explanation": f"JUDGE ERROR: {last_error}", "raw": "", "error": True, "model": model}


def git_commit_of(path: Path) -> str:
    """Short hash and commit time of the last commit that touched `path`, for the ordering record."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%h %cI", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return out or "uncommitted"
    except Exception:
        return "unknown"


def save_judge_run(judge: str, prompt_path: Path, model: str, cases: List[dict],
                   labels: Dict[str, dict], results: List[dict], per_run: List[int]) -> Path:
    """
    Writes one judge run to eval/week6/runs/. Committing this file after
    labels_25.json is what proves the labels came first.
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    record = {
        "judge": judge,
        "prompt_file": prompt_path.name,
        "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "model": model,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "labels_commit": git_commit_of(LABELS_FILE),
        "runs": len(per_run),
        "agreement_per_run": per_run,
        "results": [
            {
                "ticket_id": c["ticket_id"],
                "week5_mode": c.get("week5_mode"),
                "human": labels.get(c["ticket_id"], {}).get("label"),
                "judge": r["score"],
                "agree": r["score"] == labels.get(c["ticket_id"], {}).get("label"),
                "votes": r.get("votes", [r["score"]]),
                "error": r.get("error", False),
                "explanation": r["explanation"],
            }
            for c, r in zip(cases, results)
        ],
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RUNS_DIR / f"judge_{judge}_{stamp}.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


# ==============================================================================
# Langfuse Logging
# ==============================================================================

def week5_mode_tag(mode: str | None) -> str:
    """
    The Langfuse tag for a Week 5 mode, spelled the way the Week 5 backfill spells it.

    The eval set stores `mode_1` and `no_defect_seen`; push_traces_to_langfuse.py tags
    `mode:1` and `no-defect-seen`. Tagging the raw value gave `mode:mode_1`, so a
    `mode:1` filter found the Week 5 traces and silently missed every Week 6 case.
    """
    if not mode or mode == "no_defect_seen":
        return "no-defect-seen" if mode else "mode:unknown"
    match = re.fullmatch(r"mode_(\d+)", mode)
    return f"mode:{match.group(1)}" if match else f"mode:{mode}"


def load_saved_run(path: Path, cases: List[dict]) -> Tuple[List[dict], str]:
    """
    A committed judge run, reshaped into what call_llm_judge returns.

    Lets Langfuse show the verdicts the README reports instead of a fresh, different
    set: the judge is not deterministic at temperature 0. The saved file keeps the
    verdict, votes and explanation but not the raw output or token usage, so the
    replayed generations carry the rebuilt prompt and the explanation, and no usage.
    """
    record = json.loads(path.read_text(encoding="utf-8"))
    prompt = (EVAL_DIR / record["prompt_file"]).read_text(encoding="utf-8")
    if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != record["prompt_sha256"]:
        sys.exit(f"{record['prompt_file']} changed since {path.name} was run; replay would misreport the prompt.")
    by_id = {r["ticket_id"]: r for r in record["results"]}
    missing = [c["ticket_id"] for c in cases if c["ticket_id"] not in by_id]
    if missing:
        sys.exit(f"{path.name} has no result for {missing}")
    results = []
    for c in cases:
        r = by_id[c["ticket_id"]]
        results.append({
            "score": r["judge"], "explanation": r["explanation"], "raw": None, "error": r["error"],
            "votes": r["votes"], "model": record["model"],
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": judge_user_prompt(c)}],
        })
    return results, record["run_at"]

def log_to_langfuse(
    langfuse_client: Any,
    cases: List[dict],
    labels: Dict[str, dict],
    v1_results: List[dict],
    v2_results: List[dict],
    assertion_results: List[dict],
    run_id: str | None = None,
    replay: bool = False,
) -> None:
    if langfuse_client is None:
        print("Langfuse client not active, skipping Langfuse sync.")
        return

    print("\n[Langfuse] Syncing evaluation runs and scores to Langfuse...")
    
    dataset_name = "week6_ticket_replies"
    try:
        dataset = langfuse_client.get_dataset(name=dataset_name)
    except Exception:
        try:
            dataset = langfuse_client.create_dataset(
                name=dataset_name,
                description="Week 6 Support Ticket Replies - Validating LLM Judge Agreement and Assertions",
                metadata={"module": "Week 6 Evals", "domain": "Customer Support Tickets"},
            )
        except Exception as e:
            print(f"Could not get/create dataset: {e}")
            dataset = None

    from langfuse import propagate_attributes

    # One trace per ticket per run, grouped into a session per run. A seed of the
    # ticket id alone made every re-run stack another root span on the same trace.
    # A replay reuses the run's own timestamp, so pushing it twice updates the same traces.
    run_id = run_id or f"week6-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    for i, case in enumerate(cases):
        tid = case["ticket_id"]
        trace_id = langfuse_client.create_trace_id(seed=f"{run_id}_{tid}")
        human_label = labels.get(tid, {}).get("label", 0)
        v1 = v1_results[i]
        v2 = v2_results[i]
        asserts = assertion_results[i]
        all_asserts_passed = all(asserts.values())

        # Link to dataset if available
        if dataset:
            try:
                item_id = f"item_{tid}"
                langfuse_client.create_dataset_item(
                    dataset_name=dataset_name,
                    id=item_id,
                    input={"question": case["question"], "context": case["context"]},
                    expected_output={"label": human_label, "expected": labels.get(tid, {}).get("verdict")},
                    metadata={"week5_mode": case.get("week5_mode"), "tier": case.get("tier")},
                )
            except Exception:
                pass

        tags = ["week6", week5_mode_tag(case.get("week5_mode")), f"tier:{case.get('tier')}"]
        if case.get("is_regression"):
            tags.append("regression")
        if not all_asserts_passed:
            tags.append("assertion-failed")
        if replay:
            tags.append("replay")

        # Tags and trace name only reach the trace through propagate_attributes in
        # the v4 SDK; building the list alone left every week 6 trace untagged.
        with propagate_attributes(
            trace_name=f"week6 eval: {tid}",
            tags=tags,
            session_id=run_id,
            metadata={"ticket_id": tid, "week5_mode": case.get("week5_mode")},
        ):
            span = langfuse_client.start_observation(
                trace_context={"trace_id": trace_id},
                name=f"eval_ticket_{tid}",
                as_type="span",
                input={"question": case["question"], "context": case["context"]},
                output=case["drafted_reply"],
                metadata={
                    "ticket_id": tid,
                    "trace_id_w5": case.get("trace_id"),
                    "week5_mode": case.get("week5_mode"),
                    "assertions": asserts,
                    "human_label": human_label,
                    "judge_v1_score": v1["score"],
                    "judge_v2_score": v2["score"],
                },
            )
            span.set_trace_io(input=case["question"], output=case["drafted_reply"])

            # Each judge call as a generation, so the model, tokens and cost show up.
            # With --repeats this is the call whose verdict matched the majority.
            for name, res in (("judge_v1", v1), ("judge_v2", v2)):
                gen = span.start_observation(
                    name=name,
                    as_type="generation",
                    model=res.get("model"),
                    input=res.get("messages"),
                    output=res.get("raw") or res["explanation"],
                    usage_details=res.get("usage") or None,
                    model_parameters={"temperature": 0.0},
                    metadata={
                        "score": res["score"],
                        "votes": res.get("votes"),
                        "human_label": human_label,
                        "agrees": res["score"] == human_label,
                    },
                    level="ERROR" if res.get("error") else None,
                )
                gen.end()
            span.end()

        # Attach scores
        try:
            langfuse_client.create_score(
                trace_id=trace_id,
                name="human_ground_truth",
                value=float(human_label),
                data_type="BOOLEAN" if human_label in (0, 1) else "NUMERIC",
                comment=labels.get(tid, {}).get("reason", ""),
            )
            langfuse_client.create_score(
                trace_id=trace_id,
                name="assertions_passed",
                value=1.0 if all_asserts_passed else 0.0,
                data_type="BOOLEAN",
                comment=f"Passed {sum(asserts.values())}/{len(asserts)} assertions",
            )
            langfuse_client.create_score(
                trace_id=trace_id,
                name="judge_v1_score",
                value=float(v1["score"]),
                data_type="BOOLEAN",
                comment=v1.get("explanation", ""),
            )
            langfuse_client.create_score(
                trace_id=trace_id,
                name="judge_v2_score",
                value=float(v2["score"]),
                data_type="BOOLEAN",
                comment=v2.get("explanation", ""),
            )
            langfuse_client.create_score(
                trace_id=trace_id,
                name="judge_v1_agreement",
                value=1.0 if v1["score"] == human_label else 0.0,
                data_type="BOOLEAN",
            )
            langfuse_client.create_score(
                trace_id=trace_id,
                name="judge_v2_agreement",
                value=1.0 if v2["score"] == human_label else 0.0,
                data_type="BOOLEAN",
            )
        except Exception as exc:
            print(f"  [Langfuse] score upload failed for {tid}: {exc}")

    langfuse_sink.flush()
    print(f"[Langfuse] Synced {len(cases)} evaluation traces with assertion, label and judge scores.")
    print(f"[Langfuse Dashboard] {settings.langfuse_base_url.rstrip('/')}/project/cmts8l4k00513ad0g86x36tlp")


# ==============================================================================
# Main Runner
# ==============================================================================

def pct(n: int, d: int) -> str:
    return f"{(n / d) * 100:.0f}%" if d else "-"


def main():
    parser = argparse.ArgumentParser(description="Week 6 Support Ticket Evaluation & Judge Validation")
    parser.add_argument("--eval-set", type=Path, default=EVAL_SET)
    parser.add_argument("--labels", type=Path, default=LABELS_FILE)
    parser.add_argument("--model", type=str, default=settings.groq_model)
    parser.add_argument("--limit", type=int, default=None, help="Limit number of cases to evaluate")
    parser.add_argument(
        "--judge", choices=["v1", "v2", "both"], default="both",
        help="Which judge prompt(s) to run. 'v1' alone is the pre-iteration run.",
    )
    parser.add_argument(
        "--repeats", type=int, default=3,
        help="Runs per judge. The judge is not deterministic at temperature 0, so the verdict is a majority vote.",
    )
    parser.add_argument("--no-langfuse", action="store_true", help="Skip Langfuse telemetry sync")
    parser.add_argument(
        "--replay", nargs=2, type=Path, metavar=("V1_RUN", "V2_RUN"),
        help="Push two committed runs from eval/week6/runs/ to Langfuse without calling the judge",
    )
    args = parser.parse_args()
    if args.replay:
        replay_to_langfuse(args)
        return

    print("=" * 80)
    print("WEEK 6 EVALUATION: VALIDATE THE TICKET-REPLY JUDGE BEFORE YOU TRUST ITS NUMBER")
    print("=" * 80)

    # 1. Load data
    cases = [json.loads(line) for line in args.eval_set.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        cases = cases[:args.limit]
    labels = json.loads(args.labels.read_text(encoding="utf-8")).get("labels", {})
    missing = [c["ticket_id"] for c in cases if c["ticket_id"] not in labels]
    if missing:
        sys.exit(f"Cases without a hand label: {missing}. Label them before running the judge.")
    prediction_text = PREDICTION_FILE.read_text(encoding="utf-8").strip() if PREDICTION_FILE.exists() else ""
    judges = ["v1", "v2"] if args.judge == "both" else [args.judge]
    prompt_paths = {"v1": JUDGE_V1_PROMPT, "v2": JUDGE_V2_PROMPT}

    total_cases = len(cases)
    regressions = [c["ticket_id"] for c in cases if c.get("is_regression")]
    print(f"Loaded {total_cases} test cases from {args.eval_set.name} "
          f"({len(regressions)} verbatim regression replays: {', '.join(regressions)})")
    print(f"Loaded {len(labels)} blind human labels from {args.labels.name} "
          f"(last commit: {git_commit_of(args.labels)})")
    print(f"LLM model for judge: {args.model}")

    # 2. Deterministic assertions
    print("\n" + "-" * 80)
    print("STEP 1: DETERMINISTIC ASSERTIONS")
    print("-" * 80)
    assertion_results = [run_assertions(c, c["drafted_reply"]) for c in cases]
    print(f"Assertion criteria count : {len(ASSERTIONS)} (rule-based, no LLM)")
    print(f"Judged criteria count    : {JUDGED_CRITERIA} (binary resolution quality)")
    print("\nAssertion breakdown:")
    for name in ASSERTIONS:
        passed = sum(1 for r in assertion_results if r[name])
        print(f"  - {name:<28} : {passed:2d}/{total_cases} passed ({passed / total_cases * 100:5.1f}%)")
    for c, r in zip(cases, assertion_results):
        failed = [n for n, ok in r.items() if not ok]
        if failed:
            print(f"    {c['ticket_id']} fails: {', '.join(failed)}")

    # 3. LLM judge(s)
    groq_client = OpenAI(base_url=settings.groq_base_url, api_key=settings.groq_api_key)
    results: Dict[str, List[dict]] = {}
    per_run_agreement: Dict[str, List[int]] = {}
    for step, j in enumerate(judges, start=2):
        print("\n" + "-" * 80)
        print(f"STEP {step}: LLM JUDGE {j.upper()} ({prompt_paths[j].name}, {args.repeats} run(s))")
        print("-" * 80)
        prompt = prompt_paths[j].read_text(encoding="utf-8")
        runs = [[call_llm_judge(groq_client, prompt, case, args.model) for case in cases] for _ in range(args.repeats)]
        per_run_agreement[j] = [
            sum(1 for c, r in zip(cases, run) if r["score"] == labels[c["ticket_id"]]["label"]) for run in runs
        ]
        # The verdict used below is the majority over runs; with --repeats 1 it is the single run.
        results[j] = []
        for i, case in enumerate(cases):
            votes = [run[i]["score"] for run in runs]
            majority = 1 if sum(votes) * 2 > len(votes) else 0
            res = dict(next(run[i] for run in runs if run[i]["score"] == majority))
            res["votes"] = votes
            results[j].append(res)
            human = labels[case["ticket_id"]]["label"]
            mark = "  " if majority == human else "XX"
            flip = " (unstable)" if len(set(votes)) > 1 else ""
            print(f"  {mark} {case['ticket_id']}: judge={majority} votes={votes} human={human}{flip} | {res['explanation'][:55]}")
        saved = save_judge_run(j, prompt_paths[j], args.model, cases, labels, results[j], per_run_agreement[j])
        print(f"  -> saved {saved.relative_to(ROOT)}")

    # 4. Pass rate by Week 5 taxonomy mode
    modes = sorted({c.get("week5_mode", "unknown") for c in cases})
    header = f"{'Week 5 Mode':<16} | {'Cases':>5} | {'Assertions':>10} | {'Human':>6}"
    for j in judges:
        header += f" | {'Judge ' + j:>9}"
    print("\n" + "=" * 80)
    print("PASS RATE BY WEEK 5 TAXONOMY MODE")
    print("=" * 80)
    print(header)
    print("-" * 80)

    def row(name: str, idx: List[int]) -> str:
        n = len(idx)
        line = (f"{name:<16} | {n:>5} | {pct(sum(all(assertion_results[i].values()) for i in idx), n):>10}"
                f" | {pct(sum(labels[cases[i]['ticket_id']]['label'] for i in idx), n):>6}")
        for j in judges:
            line += f" | {pct(sum(results[j][i]['score'] for i in idx), n):>9}"
        return line

    for m in modes:
        print(row(m, [i for i, c in enumerate(cases) if c.get("week5_mode", "unknown") == m]))
    print("-" * 80)
    print(row("OVERALL", list(range(total_cases))))
    print("=" * 80)

    # 5. Agreement
    agreement: Dict[str, Tuple[int, float]] = {}
    for j in judges:
        matches = sum(1 for i, c in enumerate(cases) if results[j][i]["score"] == labels[c["ticket_id"]]["label"])
        agreement[j] = (matches, matches / total_cases * 100)
    print("\nJUDGE AGREEMENT WITH BLIND HUMAN LABELS")
    print("-" * 80)
    names = {"v1": "agreement_before", "v2": "agreement_after"}
    for j in judges:
        m, a = agreement[j]
        spread = ", ".join(f"{x}/{total_cases}" for x in per_run_agreement[j])
        print(f"  {names[j]:<17} (judge {j} vs human) : {a:5.1f}% ({m}/{total_cases} majority vote; per run: {spread})")
    if "v1" in agreement and "v2" in agreement:
        print(f"  delta                                : {agreement['v2'][1] - agreement['v1'][1]:+5.1f} pts")
    # The v2 few-shot examples are eval cases, so v2 has seen their answers. Agreement
    # on the cases it has not seen is the number that says whether the judge improved.
    shot_ids = set(re.findall(r"Ticket #(T\d+)", JUDGE_V2_PROMPT.read_text(encoding="utf-8")))
    held_out = [i for i, c in enumerate(cases) if c["ticket_id"] not in shot_ids]
    if shot_ids and held_out:
        print(f"  held-out ({len(held_out)} cases, excluding v2 few-shot {', '.join(sorted(shot_ids))}):")
        for j in judges:
            m = sum(1 for i in held_out if results[j][i]["score"] == labels[cases[i]["ticket_id"]]["label"])
            print(f"    judge {j}                            : {m / len(held_out) * 100:5.1f}% ({m}/{len(held_out)})")
    print(f"  assertions vs judged criteria        : {len(ASSERTIONS)} vs {JUDGED_CRITERIA}")
    errors = {j: sum(r.get("error", False) for r in results[j]) for j in judges}
    if any(errors.values()):
        print(f"  WARNING judge errors (counted as FAIL): {errors}")

    # 6. Disagreements
    for j in judges:
        dis = [(c, results[j][i]) for i, c in enumerate(cases) if results[j][i]["score"] != labels[c["ticket_id"]]["label"]]
        print("\n" + "-" * 80)
        print(f"DISAGREEMENTS: judge {j} vs human ({len(dis)})")
        print("-" * 80)
        for c, r in dis:
            h = labels[c["ticket_id"]]
            print(f"  {c['ticket_id']} [{c.get('week5_mode')}] human={h['verdict']} judge={'PASS' if r['score'] else 'FAIL'}")
            print(f"    Q: {c['question'][:110]}")
            print(f"    human reason: {h['reason']}")
            print(f"    judge reason: {r['explanation']}")
    if "v1" in results and "v2" in results:
        fixed = [c["ticket_id"] for i, c in enumerate(cases)
                 if results["v1"][i]["score"] != labels[c["ticket_id"]]["label"]
                 and results["v2"][i]["score"] == labels[c["ticket_id"]]["label"]]
        broke = [c["ticket_id"] for i, c in enumerate(cases)
                 if results["v1"][i]["score"] == labels[c["ticket_id"]]["label"]
                 and results["v2"][i]["score"] != labels[c["ticket_id"]]["label"]]
        print(f"\n  fixed by v2     : {', '.join(fixed) or 'none'}")
        print(f"  broken by v2    : {', '.join(broke) or 'none'}")

    if prediction_text:
        print("\n" + "-" * 80)
        print(f"PREDICTION (prediction.txt, last commit: {git_commit_of(PREDICTION_FILE)}):")
        print(f"  {prediction_text}")
        print("  Scored against the outcome in docs/week6/README.md.")

    # 7. Langfuse telemetry, only for a complete before -> after run
    if args.judge == "both" and not args.no_langfuse and langfuse_sink.enabled():
        client = langfuse_sink.get_client()
        log_to_langfuse(client, cases, labels, results["v1"], results["v2"], assertion_results)


def replay_to_langfuse(args: argparse.Namespace) -> None:
    if not langfuse_sink.enabled():
        sys.exit("Langfuse is not configured; set LANGFUSE_ENABLED and both keys in backend/.env")
    cases = [json.loads(line) for line in args.eval_set.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        cases = cases[:args.limit]
    labels = json.loads(args.labels.read_text(encoding="utf-8")).get("labels", {})
    v1, _ = load_saved_run(args.replay[0], cases)
    v2, v2_at = load_saved_run(args.replay[1], cases)
    assertion_results = [run_assertions(c, c["drafted_reply"]) for c in cases]
    stamp = datetime.fromisoformat(v2_at).strftime("%Y%m%dT%H%M%SZ")
    for name, res in (("v1", v1), ("v2", v2)):
        agree = sum(r["score"] == labels[c["ticket_id"]]["label"] for c, r in zip(cases, res))
        print(f"judge {name}: {agree}/{len(cases)} agree with the hand labels")
    log_to_langfuse(
        langfuse_sink.get_client(), cases, labels, v1, v2, assertion_results,
        run_id=f"week6-replay-{stamp}", replay=True,
    )


if __name__ == "__main__":
    main()
