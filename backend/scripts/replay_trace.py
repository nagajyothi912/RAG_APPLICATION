#!/usr/bin/env python3
"""
Replay one trace from the trace alone, and show the result beside the original.

Two strategies, and the difference between them is itself part of the Week 5
deliverable:

- `rebuild` reads the question, mode, top_k, filters and chunking configuration
  out of the trace, rebuilds the index, checks the corpus fingerprint still
  matches, re-runs retrieval, and re-sends the recorded prompt to the recorded
  model at the recorded parameters. This reproduces both halves exactly - but
  only because the collection run pinned temperature to 0. At Groq's default
  the same prompt returns differently worded text every call, so a live trace
  from the shipped app is not byte-replayable. That is a finding, not a bug in
  this script.
- `from-context` tries to replay generation from the trace's source list alone,
  without touching the corpus. It cannot: the response carries a 180-character
  preview per chunk and the prompt needs the full text. The script says so and
  falls back to re-deriving the text by (source, chunk_id), verifying each
  chunk's recorded sha256. That failure is the honest answer to "what could you
  not reconstruct".

Usage:

    python scripts/replay_trace.py --from sample --pick-seed 20260907
    python scripts/replay_trace.py --trace-id TR-0037 --out ../docs/week5/replay.md
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

DEFAULT_TRACES = ROOT / "docs" / "week5" / "traces.jsonl"
DEFAULT_SAMPLE = ROOT / "docs" / "week5" / "sample.json"

os.environ["TRACE_ENABLED"] = "false"  # replaying must not append to the file it reads
os.environ["DOCS_DIR"] = str(ROOT / "sample_documents")

from app.config import settings  # noqa: E402
from app.services.rag_service import (  # noqa: E402
    VectorStore,
    answer_with_groq,
    build_chunks,
)
from openai import OpenAI  # noqa: E402


def load_traces(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["trace_id"]] = rec
    return out


def pick(traces: dict, sample_path: Path, seed: int) -> str:
    """Seeded pick from the sampled 20, so the choice is not a choice."""
    ids = sorted(json.loads(sample_path.read_text(encoding="utf-8"))["random"])
    return random.Random(f"{seed}:replay").choice(ids)


def rebuild_store(config: dict):
    chunks = build_chunks(
        str(ROOT / "sample_documents"),
        chunk_size=config["chunk_size"],
        overlap=config["chunk_overlap"],
        strategy=config["chunk_strategy"],
    )
    store = VectorStore()
    store.index(chunks)
    return store


def fmt(value, digits=4):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--traces", type=Path, default=DEFAULT_TRACES)
    ap.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    ap.add_argument("--trace-id")
    ap.add_argument("--from", dest="source", choices=["sample", "all"], default="sample")
    ap.add_argument("--pick-seed", type=int, default=20260907)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    traces = load_traces(args.traces)
    trace_id = args.trace_id or pick(traces, args.sample, args.pick_seed)
    if trace_id not in traces:
        sys.exit(f"No trace {trace_id!r} in {args.traces}")
    trace = traces[trace_id]

    config = trace["config"]
    request = trace["request"]
    lines: list[str] = []
    w = lines.append
    verdicts: list[tuple[str, bool]] = []

    w(f"## Replay of `{trace_id}`")
    w("")
    if not args.trace_id:
        w(f"Picked by seeded draw from the sampled 20: "
          f"`random.Random(\"{args.pick_seed}:replay\").choice(sorted(sample['random']))`.")
        w("")
    w(f"**Question.** {request['question']!r}")
    w("")
    w(f"**Recorded at.** {trace['started_at']} · ticket `{trace.get('source_id','-')}` · "
      f"pool `{trace.get('pool','-')}`")
    w("")
    w("### What the trace carried")
    w("")
    w("| field | value |")
    w("| --- | --- |")
    for key, value in [
        ("mode", request["mode_effective"]),
        ("top_k", request["top_k_effective"]),
        ("filters", json.dumps(request["filters"])),
        ("chunking", f"{config['chunk_strategy']}/{config['chunk_size']}/{config['chunk_overlap']}"),
        ("embed model", config["embed_model"]),
        ("corpus fingerprint", config["corpus"]["fingerprint"]),
        ("model", trace["generation"]["model"]),
        ("params", json.dumps(trace["generation"]["params"])),
        ("prompt id", trace["generation"]["prompt_id"]),
        ("score threshold", config["score_threshold"]),
    ]:
        w(f"| {key} | `{value}` |")
    w("")

    # ---------------- retrieval replay
    print(f"Rebuilding the index at {config['chunk_strategy']}/{config['chunk_size']}/"
          f"{config['chunk_overlap']} ...")
    store = rebuild_store(config)
    same_corpus = store.fingerprint == config["corpus"]["fingerprint"]
    verdicts.append(("corpus fingerprint", same_corpus))

    filters = request["filters"] or None
    if request["mode_effective"] == "week4":
        results = store.search_hybrid(
            request["question"], top_k=request["top_k_effective"], filters=filters
        )
        replayed = [(c, s.dense_score, s.rerank_score) for c, s in results]
    else:
        results = store.search(
            request["question"], top_k=request["top_k_effective"], filters=filters
        )
        replayed = [(c, score, None) for c, score in results]

    original = trace["retrieval"]["chunks"]
    w("### Retrieval: original vs replayed")
    w("")
    w("| rank | original chunk | dense | rerank | replayed chunk | dense | rerank | |")
    w("| ---: | --- | ---: | ---: | --- | ---: | ---: | --- |")
    order_ok = True
    for i in range(max(len(original), len(replayed))):
        o = original[i] if i < len(original) else None
        r = replayed[i] if i < len(replayed) else None
        o_uid = o["chunk_uid"] if o else "-"
        r_uid = f"{r[0].source}#{r[0].chunk_id}" if r else "-"
        match = o_uid == r_uid and (
            o is None or r is None or abs((o["dense_score"] or 0) - r[1]) < 1e-4
        )
        order_ok = order_ok and match
        w(
            f"| {i+1} | `{o_uid}` | {fmt(o['dense_score']) if o else '-'} "
            f"| {fmt(o['rerank_score']) if o else '-'} | `{r_uid}` | {fmt(r[1]) if r else '-'} "
            f"| {fmt(r[2]) if r else '-'} | {'match' if match else 'DIFFERS'} |"
        )
    verdicts.append(("retrieval ranking and scores", order_ok))
    w("")

    gate_replayed = max((s for _, s, _ in replayed), default=0.0)
    gate_ok = abs(gate_replayed - (trace["retrieval"]["gate_score"] or 0)) < 1e-4
    verdicts.append(("gate score", gate_ok))
    w(f"Gate score: original `{fmt(trace['retrieval']['gate_score'])}`, "
      f"replayed `{fmt(gate_replayed)}` — {'match' if gate_ok else 'DIFFERS'}. "
      f"Refused: original `{trace['retrieval']['refused']}`, "
      f"replayed `{gate_replayed < config['score_threshold']}`.")
    w("")

    # ---------------- the from-context attempt, which is meant to fail
    w("### Replay from the trace's source list alone")
    w("")
    previews = [c["preview"] for c in original]
    truncated = [c for c in original if c["text_chars"] > len(c["preview"])]
    if truncated:
        w(f"Not possible. The trace stores a {len(previews[0]) if previews else 0}-character preview "
          f"per chunk and {len(truncated)} of {len(original)} retrieved chunks are longer than their "
          f"preview, so the prompt cannot be rebuilt from the source list. The full prompt is "
          f"recorded separately, which is why the generation replay below works; re-deriving the "
          f"chunk text from the corpus and checking it against each recorded `text_sha256` is the "
          f"fallback.")
        by_uid = {f"{c.source}#{c.chunk_id}": c for c in store.chunks}
        sha_ok = True
        import hashlib
        for c in original:
            found = by_uid.get(c["chunk_uid"])
            if found is None or hashlib.sha256(found.text.encode()).hexdigest() != c["text_sha256"]:
                sha_ok = False
        verdicts.append(("chunk text sha256 re-derived from corpus", sha_ok))
        w("")
        w(f"Re-derived chunk text matches every recorded sha256: **{sha_ok}**.")
    else:
        w("Every retrieved chunk fits inside its preview, so this trace happens to be "
          "replayable from its source list. That is a property of this trace, not of the schema.")
    w("")

    # ---------------- generation replay
    w("### Generation: original vs replayed")
    w("")
    generation = trace["generation"]
    if not generation["called"]:
        w("The model was never called: retrieval scored below the threshold and the "
          "pre-LLM gate answered. There is nothing to re-send, and the replayed answer is "
          "the same string for the same reason.")
        replay_answer = "I don't know. That isn't covered in the documents I have."
        same = replay_answer == trace["answer"]["text"]
        verdicts.append(("answer", same))
    elif not settings.api_key:
        w("Skipped: GROQ_API_KEY is not set, so the recorded prompt could not be re-sent.")
        replay_answer = None
    else:
        print("Re-sending the recorded prompt ...")
        client = OpenAI(api_key=settings.api_key, base_url=settings.groq_base_url)
        params = generation["params"] or {}
        response = client.chat.completions.create(
            model=generation["model"],
            messages=[
                {"role": "system", "content": generation["system_prompt"]},
                {"role": "user", "content": generation["user_prompt"]},
            ],
            max_tokens=params.get("max_tokens", 400),
            **({} if params.get("temperature") is None else {"temperature": params["temperature"]}),
        )
        replay_answer = (response.choices[0].message.content or "")
        same = replay_answer.strip() == (generation["raw_output"] or "").strip()
        verdicts.append(("raw model output", same))
        w(f"Re-sent the recorded prompt verbatim ({generation['context_chars']} characters of "
          f"context) to `{generation['model']}` at temperature "
          f"`{params.get('temperature')}`.")
        w("")

    w("**Original answer**")
    w("")
    w("```")
    w(trace["answer"]["text"])
    w("```")
    w("")
    if replay_answer is not None:
        w("**Replayed answer**")
        w("")
        w("```")
        w(replay_answer.strip())
        w("```")
        w("")

    w("### Verdict")
    w("")
    w("| field | result |")
    w("| --- | --- |")
    for name, ok in verdicts:
        w(f"| {name} | {'match' if ok else 'DIFFERS'} |")
    w("")

    text = "\n".join(lines)
    print()
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote {args.out}")
    sys.exit(0 if all(ok for _, ok in verdicts) else 1)


if __name__ == "__main__":
    main()
