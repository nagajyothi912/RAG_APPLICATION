# drill.md — find the refund answer nobody logged a trace id for

**Complaint, verbatim:** "a customer said it gave a wrong answer about refunds yesterday afternoon."

## Result

| | |
|---|---|
| Time-to-find (squadmate-timed) | **`__:__` — not yet run.** See "What this is and is not" below. |
| Tool time for the query that surfaced it | **0.09 s** wall (20 ms inside the search), 21 candidates out of 3,001 traces |
| Slice that found it | **time window + text**, where the text only matched because **`context_ids`** is indexed |
| Found trace | `cedbb74dcb434af781896fdebf4ac3e2`, full record in [trace.json](trace.json) |

The one command:

```bash
cd backend
python scripts/find_trace.py --log data/traces/drill/chat_traces.jsonl \
    --text refund --day yesterday --hours 12-18 --tz-offset 5.5 --limit 100
```

It prints 21 requests. 20 give a correct refund answer ("7 days", "10 business days", "not refundable for OTT add-ons"). One says:

```
2026-11-23T10:10:25.000Z  cedbb74dcb43  user=user  v1  question  answered $0.000203  9869ms
    Q: does the 30 day money back guarantee apply to me
    A: I don't know based on the provided documents.
    ctx: account_management.md#3 account_management.md#4 account_management.md#1 account_management.md#0 refund_policy.txt#0
```

The answer is wrong in a specific way: the refund policy **was** in the retrieved context (last, `refund_policy.txt#0`), the customer asked about refunds, and the app refused as if the documents said nothing.

## The log field that made this findable (and what would have cost the time)

The word "refund" appears in **neither** the question ("…30 day money back guarantee…") **nor** the answer ("I don't know…"). It appears only in the retrieved context ids. Checked against the index:

| text search over | rows in the 12:00–18:00 window | contains the bad answer |
|---|---|---|
| question + answer only | 20 | **no** |
| `context_ids` (or all three) | 21 | **yes** |

So the exact log field whose absence would have cost the time is **`context_ids`** (the flat list of retrieved chunk ids per request). A log or index over inputs and outputs alone returns 20 plausible, correct-looking answers and misses the failure — the "searching only inputs" trap from the brief, in a form where searching outputs doesn't save you either.

## What this is and is not

**This is a dry run of the tooling, not a valid timed drill.** I wrote `week11_drill.py plant`, so I knew the question and the failure before I started; the brief is explicit that finding something because you remember it is "memory, not tooling". The drill still did its job as a test of the tooling, and found two bugs in it (below). The scored number needs a squadmate:

1. Squadmate re-seeds and plants (the finder does not run these):
   ```bash
   python scripts/week11_drill.py seed --tz-offset 5.5      # 3,000 background requests over 7 days (synthetic)
   python scripts/week11_drill.py plant --tz-offset 5.5     # one REAL v1 refund answer, random time yesterday 12:00-18:00 local
   ```
2. Squadmate gives the finder only the complaint above and starts a stopwatch; the finder uses `find_trace.py` only, no opening the JSONL.
3. Squadmate records mm:ss, the slice used, and their name here: `Timed by: ________  Time: __:__  Slice: ________`.
4. `python scripts/week11_drill.py reveal` confirms the trace id.

What is real in the drill log: the planted trace is a real request through the live pipeline on the Week 10 prompt (v1), real model answer, real token usage and latency; only its timestamp, id and user were rewritten. The other 3,000 requests are **synthetic** (12 knowledge-base Q&A templates, token counts/latencies drawn around values measured on real requests) but are built by the app's own `build_chat_record`, so they have exactly the shape of live traces.

## The found trace at a glance

From [trace.json](trace.json) (re-planted on 2026-11-24 after the two trace fixes below):

| span | starts at | latency | tokens in / out | cost |
|---|---:|---:|---:|---:|
| retrieval (local: embed + BM25 + RRF + rerank) | 0 ms | 7,924 ms | – | $0 |
| generation (`openai/gpt-oss-120b`) | 7,924 ms | 1,748 ms | 680 / 169 | $0.000203 |
| other (prompt build, cache lookup, trace write) | 9,672 ms | 197 ms | – | $0 |
| **total** (`started_at` 10:10:25.000Z → `finished_at` 10:10:34.868Z) | | **9,869 ms** | 849 | **$0.000203** |

Prompt version **v1** (`prompt_id` `v1-cfc04156c4e7`). Retrieved context ids, in rank order: `account_management.md#3`, `#4`, `#1`, `#0`, **`refund_policy.txt#0`** (the policy that answers the question, ranked last). `finish_reason: stop`, so the model chose to refuse; it was not cut off.

## Bugs the drill found in my own tooling

1. **Stale index.** After re-seeding, the finder returned the *previous* planted trace. `ensure_index` only compared row counts, and the re-seeded log had the same number of lines. Fixed (rebuild when the log is newer than the index) with a regression test, `test_find_trace_rebuilds_a_stale_index_even_when_the_row_count_is_unchanged`. A drill answer served from a stale index is the worst kind of wrong: confident and plausible.
2. **Plant placed in the wrong day.** `plant` mixed the UTC date with local hours, so "yesterday afternoon" landed two days back. Fixed to compute the local day, then convert to UTC.
3. **`finished_at` equal to `started_at`.** Rewriting the timestamp set both to the same second, so an 8.6 s request looked instant. Fixed: `finished_at = started_at + latency_ms.total` (test: `test_drill_records_finish_after_they_start`).
4. **Spans did not add up to the total.** About 180 ms per request (prompt build, cache lookup, trace write) sat in no span. `build_spans` now adds an `other` span for the remainder (test: `test_spans_add_up_to_the_total_with_the_remainder_as_other`).

## Slices available

| Slice | Flag | Backed by |
|---|---|---|
| time | `--since/--until`, or `--day yesterday --hours 12-18 --tz-offset 5.5` | `started_at` index |
| user | `--user` | `session.user` (from the signed-in account) |
| prompt version | `--prompt-version v1` | `generation.prompt_version` |
| input type | `--input-type follow_up` | `input_type` (`question` / `follow_up`) |
| cost / latency outlier | `--outliers`, `--min-cost`, `--slowest` | `cost_usd.total`, `latency_ms.total` |
| words in question or answer | `--text` | FTS5 over question, answer, **context ids** |
| retrieved article | `--context refund_policy.txt#0` | `context_ids` |

Honest limit: this app has two fixed accounts (`user`, `admin`), so the **user** slice narrows very little here. In a real multi-customer deployment it would be the first slice to use once the time window is known.

## Bonus (not done)

The bonus asks for a second plant and a beaten time, both timed by a squadmate. Not attempted. The field that closes the gap is already shipped: `context_ids`, plus the index.
