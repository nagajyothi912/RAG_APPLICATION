#!/usr/bin/env python3
"""
Push the committed Week 5 traces into Langfuse.

The error analysis is pinned to `docs/week5/traces.jsonl` by sha256: the sampler
draws from it, the replay script reads it, the taxonomy quotes its trace ids, and
the test suite asserts against all of that. Re-running the traffic to populate
Langfuse would produce a *different* 148 traces, break the pin, and orphan every
id in the write-up. So this backfills the traces that were actually analysed
instead of generating new ones.

It is safe to run more than once. Langfuse trace ids are derived from the local
`TR-0037` labels with `create_trace_id(seed=...)`, which is deterministic, so a
second run updates the same traces rather than duplicating them.

Sampled traces are tagged so the write-up is navigable from the Langfuse UI:

    week5              every backfilled trace
    sampled-random     one of the 20 that were open-coded
    sampled-demo       one of the 10 in the bonus
    mode:<n>           the failure mode assigned in taxonomy.md
    no-defect-seen     read and found clean

and each sampled trace carries a `week5_open_coding` score comment holding the
verbatim observation sentence, so the reading sits next to the trace it came from.

Usage:

    python scripts/push_traces_to_langfuse.py            # all 148
    python scripts/push_traces_to_langfuse.py --sampled-only
    python scripts/push_traces_to_langfuse.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

TRACES = ROOT / "docs" / "week5" / "traces.jsonl"
SAMPLE = ROOT / "docs" / "week5" / "sample.json"
NOTES = ROOT / "docs" / "week5" / "notes.md"
TAXONOMY = ROOT / "docs" / "week5" / "taxonomy.md"

os.environ.setdefault("LANGFUSE_ENABLED", "true")

from app.config import settings  # noqa: E402
from app.services import langfuse_sink  # noqa: E402


def load_open_coding() -> dict[str, str]:
    """trace_id -> the verbatim sentence written about it."""
    if not NOTES.exists():
        return {}
    text = NOTES.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for match in re.finditer(r"^\d+\.\s+`(T[RD]-\d+)`\s+[-—]\s+(.+)$", text, re.M):
        out[match.group(1)] = match.group(2).strip()
    return out


def load_modes() -> dict[str, str]:
    """
    trace_id -> mode label, read from the 'trace to mode' table in notes.md.

    Parsed rather than hardcoded so the tags cannot drift from the taxonomy.
    """
    if not NOTES.exists():
        return {}
    text = NOTES.read_text(encoding="utf-8")
    section = text.split("### 4.1 Trace to mode")
    if len(section) < 2:
        return {}
    section = section[1].split("### 4.2")[0]
    out: dict[str, str] = {}
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 2:
            continue
        label, ids = cells
        number = re.match(r"^(\d+)\.", label)
        tag = f"mode:{number.group(1)}" if number else "no-defect-seen"
        for tid in re.findall(r"`(T[RD]-\d+)`", ids):
            out[tid] = tag
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--traces", type=Path, default=TRACES)
    ap.add_argument("--sampled-only", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--replace",
        action="store_true",
        help="delete these traces before pushing, so stale tags and scores go away",
    )
    args = ap.parse_args()

    if not args.dry_run and not langfuse_sink.enabled():
        sys.exit(
            "Langfuse is not configured. Set LANGFUSE_ENABLED=true plus "
            "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in backend/.env"
        )

    records = [
        json.loads(line)
        for line in args.traces.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sample = json.loads(SAMPLE.read_text(encoding="utf-8")) if SAMPLE.exists() else {}
    sampled_random = set(sample.get("random", []))
    sampled_demo = set(sample.get("demo", []))
    coding = load_open_coding()
    modes = load_modes()

    if args.sampled_only:
        keep = sampled_random | sampled_demo
        records = [r for r in records if r["trace_id"] in keep]
    if args.limit:
        records = records[: args.limit]

    print(f"traces file : {args.traces}")
    print(f"pushing     : {len(records)} records")
    print(f"open coding : {len(coding)} sentences, {len(modes)} mode assignments")
    print(f"target      : {settings.langfuse_base_url} ({settings.langfuse_environment})")
    if args.dry_run:
        for r in records[:5]:
            tags = _tags(r, sampled_random, sampled_demo, modes)
            print(f"  {r['trace_id']}  tags={tags}  coded={r['trace_id'] in coding}")
        print("dry run, nothing sent")
        return

    if args.replace:
        # Langfuse MERGES tags and scores when a trace is updated, so a rename
        # leaves the old name behind: re-pushing after changing `mode:week4` to
        # `retrieval:week4` yields a trace carrying both. Deleting first is the
        # only way to actually retire a tag. Safe here because every trace is
        # reproducible from the committed, sha256-pinned traces.jsonl, and the
        # ids are derived, so they come back at the same URLs.
        client = langfuse_sink.get_client()
        ids = [client.create_trace_id(seed=r["trace_id"]) for r in records]
        print(f"deleting {len(ids)} traces before re-push ...")
        for i in range(0, len(ids), 50):
            client.api.trace.delete_multiple(trace_ids=ids[i : i + 50])

        # Deletion is asynchronous. Pushing straight away races it: the delete
        # job catches up mid-push and removes traces that were just written,
        # which leaves the project short and half-tagged. Wait for the tag to
        # drain to zero before writing anything back.
        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(10)
            try:
                left = client.api.trace.list(tags=["week5"], limit=1).meta.total_items
            except Exception:
                continue
            print(f"  {left} still present ...")
            if left == 0:
                break
        else:
            sys.exit("Deletion did not finish within 5 minutes; re-run --replace.")
        time.sleep(10)
        print("  deletion complete")

    sent = 0
    for n, record in enumerate(records, start=1):
        tags = _tags(record, sampled_random, sampled_demo, modes)
        trace_id = langfuse_sink.emit(record, extra_tags=tags)
        if trace_id is None:
            print(f"  {record['trace_id']}: emit failed, stopping")
            break
        sent += 1
        sentence = coding.get(record["trace_id"])
        if sentence:
            _attach_open_coding(trace_id, record, sentence, modes)
        if n % 25 == 0:
            print(f"  {n}/{len(records)} ...")
            langfuse_sink.flush()

    langfuse_sink.flush()
    print(f"\nsent {sent} traces")
    if sampled_random:
        example = sorted(sampled_random)[0]
        print(f"example: {example} -> {langfuse_sink.trace_url(example)}")
    print("Filter the project by the 'week5' tag, or by 'sampled-random' for the 20 that were read.")


def _tags(record: dict, sampled_random: set, sampled_demo: set, modes: dict) -> list[str]:
    tags = ["week5"]
    tid = record["trace_id"]
    if tid in sampled_random:
        tags.append("sampled-random")
    if tid in sampled_demo:
        tags.append("sampled-demo")
    if tid in modes:
        tags.append(modes[tid])
    return tags


def _attach_open_coding(trace_id: str, record: dict, sentence: str, modes: dict) -> None:
    """
    The observation sentence, stored next to the trace it describes.

    A numeric score is what makes it filterable and chartable in the UI; the
    sentence rides along as the comment, which is the part a human reads.

    1.0 means a failure mode was assigned, 0.0 means the trace was read and found
    clean, so the score's mean over a set of traces is its defect rate directly.
    The name has to agree with the polarity: an earlier version called this
    `week5_defect` and scored a defect as 0.0, which made every chart built on it
    read backwards.
    """
    client = langfuse_sink.get_client()
    if client is None:
        return
    try:
        client.create_score(
            trace_id=trace_id,
            name="week5_has_defect",
            value=1.0 if modes.get(record["trace_id"], "").startswith("mode:") else 0.0,
            data_type="NUMERIC",
            comment=sentence,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"    score failed for {record['trace_id']}: {exc}")


if __name__ == "__main__":
    main()
