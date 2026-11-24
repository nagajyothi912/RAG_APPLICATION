#!/usr/bin/env python3
"""
Week 11 failure -> test suite.

Every real production failure becomes a case in eval/week11/regression_cases.jsonl
and this script re-runs the whole file, so a fix for one case cannot quietly
break another. A case passes only if every check it carries passes:

  retrieval  `expect_chunks`: each `file#chunk_id` must be in the retrieved set
             for the case's mode. Deterministic, no model call.
  generation `answer_matches` / `answer_not_matches` (regexes): checked on real
             answers at the production temperature setting (unset), 3 samples per
             case, all of which must pass. Skipped with --no-generate.

Prints one line per case and a final `PASS n/N` count. Exit code 1 if any case
fails, so CI and `pytest` can gate on it.

    python scripts/run_week11_suite.py [--no-generate] [--ids F01,R01] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

CASES = BACKEND / "eval" / "week11" / "regression_cases.jsonl"


def load_cases(path: Path = CASES) -> list[dict]:
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]


def _norm(text: str) -> str:
    """The model emits narrow no-break spaces and non-breaking hyphens ("7\u202fdays");
    a check that fails on typography is a broken check, not a failing answer."""
    for ch in ("\u202f", "\u00a0", "\u2009"):
        text = text.replace(ch, " ")
    for ch in ("\u2011", "\u2010", "\u2013"):
        text = text.replace(ch, "-")
    return text


def check_case(service, case: dict, generate: bool, samples: int = 1) -> dict:
    """A case passes only if retrieval passes AND every one of `samples` answers passes."""
    mode = case.get("mode", "week4")
    results = service.retrieve(case["question"], mode=mode)
    uids = [f"{c.source}#{c.chunk_id}" for c, _ in results]
    failures: list[str] = []
    for want in case.get("expect_chunks", []):
        if not any(u.endswith(want) for u in uids):
            failures.append(f"retrieval: {want} not in top-{len(uids)} {uids}")
    answers: list[str] = []
    if generate:
        for n in range(samples):
            answer = _norm(service.ask(case["question"], mode=mode)["answer"])
            answers.append(answer)
            tag = f"[sample {n + 1}/{samples}] " if samples > 1 else ""
            for pat in case.get("answer_matches", []):
                if not re.search(pat, answer, re.IGNORECASE | re.MULTILINE):
                    failures.append(f"{tag}answer does not match /{pat}/")
            for pat in case.get("answer_not_matches", []):
                if re.search(pat, answer, re.IGNORECASE | re.MULTILINE):
                    failures.append(f"{tag}answer matches forbidden /{pat}/")
    return {"id": case["id"], "kind": case.get("kind"), "ok": not failures, "failures": failures,
            "retrieved": uids, "answer": answers[0] if answers else None, "answers": answers}


def run_suite(service, cases: list[dict], generate: bool, samples: int = 1) -> list[dict]:
    return [check_case(service, c, generate, samples) for c in cases]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-generate", action="store_true")
    ap.add_argument("--ids")
    ap.add_argument("--samples", type=int, default=3,
                    help="answers generated per case; a case must pass on every one (default 3)")
    ap.add_argument("--temperature", type=float, default=None,
                    help="default: unset, exactly as production runs. 0 reproduces the Week 5-6 eval setting.")
    ap.add_argument("--label", default="")
    ap.add_argument("--out")
    args = ap.parse_args()

    from app.config import settings
    # Production sends no temperature. The F01 failure only reproduces that way: at
    # temperature 0 the same prompt answers correctly, which is how it escaped every
    # earlier (temperature-pinned) eval.
    settings.groq_temperature = args.temperature
    from app.services.rag_service import PROMPT_ID, get_rag_service

    service = get_rag_service()
    cases = load_cases()
    if args.ids:
        keep = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in keep]
    generate = not args.no_generate
    if generate and not service.llm_configured:
        print("GROQ_API_KEY not set: run with --no-generate", file=sys.stderr)
        return 2

    lines = [f"# Week 11 suite {args.label}".rstrip(), f"prompt_id={PROMPT_ID} temperature={args.temperature} samples={args.samples if generate else 0} generate={generate} corpus={service.store.fingerprint}"]
    results = []
    for case in cases:
        r = check_case(service, case, generate, args.samples)
        results.append(r)
        lines.append(f"{'PASS' if r['ok'] else 'FAIL'}  {r['id']}  [{r['kind']}]  {case['question']}")
        for f in r["failures"]:
            lines.append(f"        - {f}")
        if generate and not r["ok"] and r["answer"]:
            lines.append(f"        answer: {r['answer'][:160]!r}")
        if generate:
            time.sleep(1.0)
    passed = sum(r["ok"] for r in results)
    lines.append(f"PASS {passed}/{len(results)}")
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
