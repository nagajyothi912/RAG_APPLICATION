#!/usr/bin/env python3
"""
Draw a seeded random sample of traces, provably.

Half of a fix ordering is frequency, and a frequency measured over a sample you
picked by hand is fiction. So the draw is seeded, published, and re-runnable by
anyone holding the trace file.

Three properties of the algorithm are deliberate:

- **Ids are sorted before sampling.** `random.sample` depends on the order of
  the population it is handed, so sampling the file in append order would mean a
  `--resume` run that reordered lines silently moved the sample.
- **Each pool gets its own RNG stream**, seeded `"{seed}:{pool}"`. With one
  shared stream, adding the bonus draw later would perturb the random 20 and rot
  every trace id already quoted in the taxonomy.
- **The sample is pinned to the trace file's sha256.** Regenerating the traces
  then breaks loudly, instead of the sample quietly describing a file that no
  longer exists.

Usage:

    python scripts/sample_traces.py --seed 20260907 --n 20 --demo-n 10 --markdown
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
DEFAULT_TRACES = ROOT / "docs" / "week5" / "traces.jsonl"
DEFAULT_OUT = ROOT / "docs" / "week5" / "sample.json"

ALGORITHM = (
    "random.Random(f'{seed}:{pool}').sample(sorted(trace_ids_in_pool), n), "
    "sorted for presentation"
)


def load_traces(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def draw(traces: list[dict], pool: str, seed: int, n: int) -> list[str]:
    ids = sorted(t["trace_id"] for t in traces if t.get("pool") == pool)
    if n > len(ids):
        sys.exit(f"Cannot draw {n} from pool {pool!r}: only {len(ids)} traces.")
    rng = random.Random(f"{seed}:{pool}")
    return sorted(rng.sample(ids, n))


def describe(trace: dict) -> dict:
    request = trace["request"]
    filters = request.get("filters") or {}
    scope = filters.get("source") or filters.get("product_area") or "-"
    return {
        "trace_id": trace["trace_id"],
        "source_id": trace.get("source_id", ""),
        "mode": request["mode_effective"],
        "top_k": request["top_k_effective"],
        "filter": scope,
        "status": trace["outcome"]["status"],
        "question": trace["request"]["question"],
    }


def markdown_table(rows: list[dict]) -> str:
    out = ["| trace_id | ticket | mode | top_k | filter | question |",
           "| --- | --- | --- | ---: | --- | --- |"]
    for r in rows:
        question = r["question"].replace("|", "\\|")
        if len(question) > 96:
            question = question[:93] + "..."
        out.append(
            f"| `{r['trace_id']}` | {r['source_id']} | {r['mode']} | {r['top_k']} "
            f"| {r['filter']} | {question} |"
        )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--traces", type=Path, default=DEFAULT_TRACES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--demo-n", type=int, default=10)
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()

    traces = load_traces(args.traces)
    by_id = {t["trace_id"]: t for t in traces}
    digest = hashlib.sha256(args.traces.read_bytes()).hexdigest()

    picked = {
        "random": draw(traces, "random", args.seed, args.n),
        "demo": draw(traces, "demo", args.seed, args.demo_n),
    }

    sample = {
        "seed": args.seed,
        "algorithm": ALGORITHM,
        "python": platform.python_version(),
        "traces": str(args.traces.relative_to(ROOT)),
        "traces_sha256": digest,
        "pool_sizes": {
            pool: sum(1 for t in traces if t.get("pool") == pool)
            for pool in sorted({t.get("pool") for t in traces if t.get("pool")})
        },
        **picked,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8")

    print(f"traces      {args.traces}")
    print(f"sha256      {digest}")
    print(f"seed        {args.seed}")
    print(f"pools       {sample['pool_sizes']}")
    for pool, ids in picked.items():
        print(f"\n{pool} ({len(ids)}):\n  " + " ".join(ids))
    if args.markdown:
        for pool, ids in picked.items():
            print(f"\n### {pool}\n")
            print(markdown_table([describe(by_id[i]) for i in ids]))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
