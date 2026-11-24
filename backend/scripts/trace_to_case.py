#!/usr/bin/env python3
"""
Turn a logged bad answer into a regression-case skeleton (the failure -> test step).

    python scripts/trace_to_case.py <trace_id> [--log FILE] [--id F03] >> eval/week11/regression_cases.jsonl

Pre-fills what the trace knows: the question, the retrieval mode, the chunks that
were retrieved, the prompt version that produced the bad answer and the bad answer
itself. It deliberately does NOT guess what the right answer is. `answer_matches`,
`answer_not_matches` and `expect_chunks` come out as TODO placeholders that make
the suite fail loudly until a person fills them in, because a case whose
expectation was auto-generated from the bad answer would pass on the bug.

Then: run `scripts/run_week11_suite.py`, watch the new case go RED, fix, watch it go GREEN.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def skeleton(rec: dict, case_id: str) -> dict:
    return {
        "id": case_id,
        "kind": "failure",
        "source": f"trace {rec['trace_id']} ({rec['started_at']}, prompt {rec['generation'].get('prompt_version')})",
        "question": rec["request"]["question"],
        "mode": rec["request"].get("mode_effective", "week4"),
        "observed_bad_answer": rec["answer"]["text"],
        "observed_context_ids": rec.get("context_ids", []),
        "expect_chunks": ["TODO: file#chunk the answer should come from"],
        "answer_matches": ["TODO: regex the correct answer must match"],
        "answer_not_matches": ["TODO: regex the bad answer matches"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_id")
    ap.add_argument("--log", type=Path, default=BACKEND / "data" / "traces" / "chat_traces.jsonl")
    ap.add_argument("--id", default="F00")
    a = ap.parse_args()
    for line in open(a.log, encoding="utf-8"):
        if a.trace_id in line[:200]:
            rec = json.loads(line)
            if rec["trace_id"].startswith(a.trace_id):
                print(json.dumps(skeleton(rec, a.id), ensure_ascii=False))
                return 0
    print("trace not found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
