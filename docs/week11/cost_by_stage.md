# cost_by_stage.md — cost per query, by stage

All dollar figures are **computed**: tokens from the model's `usage` × the price table in [`app/services/pricing.py`](../../backend/app/services/pricing.py) (`openai/gpt-oss-120b`, $0.15 / $0.60 per million input / output tokens, the same constants the Week 10 race used). They are not read off a Groq bill. Check them against the Groq usage page before quoting them as money.

## 1. The drilled request (the planted refund answer, prompt v1)

Trace `cedbb74dcb43…`, from `python scripts/cost_report.py --log data/traces/drill/chat_traces.jsonl --trace cedbb74dcb43`:

| stage | cost | share | time | tokens |
|---|---:|---:|---:|---:|
| retrieval (embed + BM25 + RRF + rerank, local) | $0.000000 | 0% | **7,924 ms** | – |
| generation (Groq, 680 in / 169 out) | $0.000203 | 100% | 1,748 ms | 849 |
| tools | $0.000000 | 0% | 0 ms | – |
| rewrite (follow-up rewrite; none on this request) | $0.000000 | 0% | 0 ms | – |
| other (prompt build, cache lookup, trace write) | $0.000000 | 0% | 197 ms | – |
| **total** | **$0.000203** | | 9,869 ms | 849 |

Reading it: all of the money is generation (input $0.000102, output $0.000101). Retrieval costs **no dollars** (MiniLM and the cross-encoder run on the app's own CPU) but **80% of this request's time**: 7.9 s is the cross-encoder loading lazily on the first `week4` request after a process start. That is a cold-start cost the customer pays once per deploy, and it only shows up because spans are timed per stage. `tools` is 0 because `/api/chat` calls no tools; it is a real column so the same report works for the tool-calling assistant once that path is traced (it is not yet).

## 2. Across real requests (prompt v2, live Groq, production temperature)

From the cost experiment's cache-off arms ([`scripts/week11_cost_experiment.py`](../../backend/scripts/week11_cost_experiment.py); raw traces in `backend/data/traces/cost_experiment/`, gitignored):

| sequence | requests | mean cost / request | p95 | mean tokens in / out | generation share of cost |
|---|---:|---:|---:|---:|---:|
| organic (Week 5 "random" pool, in order) | 30 | **$0.000306** | $0.000384 | 874 / 328 | 100% |
| FAQ-shaped | 40 | **$0.000252** | $0.000364 | 874 / 202 | 100% |

Input is 40–52% of the money, output the rest. **Output tokens are expensive here for a bad reason:** 10 of the 28 organic model calls (36%) stopped on `finish_reason: "length"`, i.e. hit the 400-token cap (`MAX_TOKENS`; for this model the cap is shared with hidden reasoning tokens). Those answers are cut off mid-sentence, and one came back empty and was replaced by the refusal fallback. That is a **user-visible failure the logs now expose and nothing tests for yet**: it is the next case for the failure → test loop, deliberately not fixed in this task.

## 3. The improvement: exact-match answer cache

**One change, one variable.** Same request sequence replayed twice, only `CACHE_ENABLED` differs. Implementation: `RagService.ask` ([rag_service.py](../../backend/app/services/rag_service.py)), key = normalised question + retrieval settings + `PROMPT_ID` + model + temperature + corpus fingerprint, TTL 1 h, 256 entries. Off by default.

| sequence | repeat rate | cache hits | mean cost / request, off → on | change |
|---|---:|---:|---|---:|
| FAQ-shaped | 60% (an **assumption**, see below) | 24 / 40 | $0.000252 → $0.000107 | **−57.7%** |
| organic | 0% (measured) | 0 / 30 | $0.000306 → $0.000308 | **+0.5%** (noise) |

**Attribution by stage.** The whole saving is the generation stage: each of the 24 hits skipped one Groq call (24 × ~$0.00024 ≈ $0.0058 of the $0.0058 saved). Retrieval cost was $0 before and after; a hit also skips retrieval *time* (mean 427 → 130 ms). Nothing else changed between the arms, so the saving cannot have come from anywhere else.

**What this does and does not show.**

- The saving equals the repeat rate. The 60% FAQ sequence is **constructed** (8 FAQ questions ×4 + 8 singles) to show the mechanism; it is not a measurement of this app's users. On the one real-shaped traffic file we have, the organic pool, **no question repeats** and the cache saved nothing. In `docs/week5/traces.jsonl` the only repeats (9.5% of rows) are the demo pools asking the same questions twice. Before relying on this lever, measure the repeat rate on real traffic.
- Latency columns in these runs are inflated by Groq 429 back-off (the sequence ran at ~2× the 8,000 tokens/min cap, see [tenx.md](tenx.md)); cost columns are not affected.
- A cache hit is still logged as its own trace (`answer.source = "cache"`, cost 0), so it stays findable.
- Not cached: refusals, "I don't know" answers, and answers that stopped on `length`. An entry also stops matching when the prompt version or the corpus changes, with no purge step (tests: `test_a_prompt_bump_or_new_document_stops_old_cache_entries_matching`, `test_an_answer_the_model_was_cut_off_in_is_never_cached`).

### Why not a semantic cache

Not built; the reason is measured. MiniLM cosine between paraphrases that deserve the same answer vs questions one number apart that deserve different answers:

| pair | cosine |
|---|---:|
| "does the 30 day money back guarantee apply to me" vs "is there a 30 day money back guarantee?" (same answer) | 0.903 |
| "Can I get a refund 7 days after installation?" vs "…30 days after installation?" (different answers) | **0.891** |
| "I'm on day 20…" vs "I'm on day 5, can I get a full refund?" (different answers) | 0.874 |

No similarity threshold separates the first row from the second. On a refund policy that is the difference between "yes" and "no", so a semantic cache would serve wrong refund answers with a straight face. Exact match it is.

## 4. Other levers, not tried

Model routing to `gpt-oss-20b` (half the per-token price) for high-confidence retrievals; lowering `top_k` (but the refund policy ranks 5th for the F01 question, so it would remove the evidence); prompt caching (the static system prompt is ~100 tokens, too small to matter). None was measured, so none is claimed.
