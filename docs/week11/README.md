# Week 11 — Task Set A: observability, cost, and the failure → test loop

Brief: [../assignments/W11-Task-Set-A.md](../assignments/W11-Task-Set-A.md) · Week brief: *Production — Observability, Cost & the Failure → Test Loop*.

## Status at a glance

| Deliverable | File | Status |
|---|---|---|
| Per-request logging with per-span time/cost, prompt version, context ids | [`tracing.py`](../../backend/app/services/tracing.py), [trace.json](trace.json) | **Done** |
| Find a planted bad refund answer from a vague complaint | [drill.md](drill.md), [`find_trace.py`](../../backend/scripts/find_trace.py) | **Tooling done and dry-run; the squadmate-timed mm:ss is NOT done** |
| Failure → eval case, RED then GREEN with pass counts | [fix_and_rollout.md](fix_and_rollout.md), [evidence/](evidence/) | **Done: 8/10 RED → 10/10 GREEN** |
| Fix + prompt version bump + two-line canary/rollback | [fix_and_rollout.md](fix_and_rollout.md) | **Done** (v1 → v2); canary is a plan, there is no traffic splitter |
| Cost per query by stage, one measured improvement | [cost_by_stage.md](cost_by_stage.md) | **Done**: −57.7% on FAQ-shaped traffic, **0% on organic traffic** |
| 10× plan with a number | [tenx.md](tenx.md) | **Done**: rate limit breaks first, 5.5× over cap |
| Bonus: second plant, beat own time | – | Not done (needs a squadmate) |

## Week 10 review (what was there before this week)

All six Week 10 deliverables exist and the Week 10 tests pass: `race_table.md`, `handoffs.log`, the multiplier line, `failure_case.md`, `verdict.md`, and the bonus AgentCard + A2A lifecycle, plus the admin `#week10` page ([../week10/README.md](../week10/README.md)). Headline: squad vs single agent, 8/10 vs 7/10, tokens 32,874 vs 53,462, cost $0.000875 vs $0.001191, p99 7.5 s vs 18.4 s; verdict KEEP, conditionally.

What Week 10 left **open**, which I checked in the code and did not touch:

| Condition from `verdict.md` | State now |
|---|---|
| Fix the 300-token reply cap that truncated 2 race replies | **Open**: `max_tokens=300` is still in `ticket_reply_app/tools.py:535` |
| Pass structured account facts so ₹ is not rendered as $ | Open (not checked further) |
| Pause for a human when a worker fails instead of sending a partial reply | Open: documented in `a2a_lifecycle.md`, not implemented |

The first one matters for Week 11: Week 11's own logs found the **same class of bug** on the main chat path (below).

## What Week 11 needed, and what the app already had

| Week 11 topic | Before this week | Now |
|---|---|---|
| What to log per request | Week 5 JSONL: question, retrieved chunks with scores, rendered prompt, raw output, model params, latency (`TRACE_ENABLED`) | Adds **who** (`session.user`, `session_id`), **input type** (`question` / `follow_up`), **cost** (total and per stage), **tokens**, flat **`context_ids`**, **cache** flag. Schema 1 → 2, additive only |
| Traces & spans | One lump: `latency_ms.{retrieval,generation,total}` | **`spans[]`**: `rewrite`, `retrieval`, `generation`, `other` (the remainder, so spans add up to the total), each with `start_ms`, `latency_ms`, tokens in/out, `cost_usd`, model, attrs |
| LangSmith / Phoenix / OpenTelemetry | Langfuse sink (`langfuse_sink.py`) | Unchanged. The new spans are **not** pushed to Langfuse and nothing emits OpenTelemetry. Gap |
| The support drill | Nothing could find a past answer except reading the JSONL | SQLite index beside the log + [`find_trace.py`](../../backend/scripts/find_trace.py) (time, user, prompt version, input type, cost outlier, words, retrieved article) + [`week11_drill.py`](../../backend/scripts/week11_drill.py) |
| Cost per query | Only the Week 10 race measured it | Every trace has it, by stage; [`cost_report.py`](../../backend/scripts/cost_report.py) |
| Prompt caching | – | Not applicable: the static system prompt is ~100 tokens |
| Semantic caching | – | **Evaluated and rejected with a measurement** (cosine 0.903 for a paraphrase vs 0.891 for "7 days" vs "30 days") |
| Exact caching | – | Built, off by default, measured |
| Model routing (LiteLLM) | `ASSISTANT_MODEL` lets the assistant use a different model | Not built, not measured |
| Fallbacks & rate limits | Week 10's `MeteredClient` absorbs 429s for the race only | **Gap on `/api/chat`**: the OpenAI client retries 429s silently, twice, which the traces show as latency |
| Data flywheel | Week 5 taxonomy is hand-written | `trace_to_case.py` turns a trace into a case skeleton; `run_week11_suite.py` is the gate |
| The 10× plan | – | [tenx.md](tenx.md) |
| Fine-tuning (last resort) | – | Not applicable: the failure fixed this week was one sentence of prompt |

## How each piece maps to this app, and to real use

| Real situation | Command / feature | Why it works |
|---|---|---|
| "It gave a wrong answer about refunds yesterday afternoon" | `find_trace.py --text refund --day yesterday --hours 12-18 --tz-offset 5.5` | Time-window index, and the words are searched in question, answer **and retrieved context ids** |
| "Did the new prompt make things worse?" | `find_trace.py --prompt-version v1` vs `v2` | Every trace carries the prompt version and a derived SHA |
| "The bill jumped" | `find_trace.py --outliers`, `cost_report.py` | Per-request and per-stage cost |
| "Which answers used the refund policy?" | `find_trace.py --context refund_policy.txt#0` | Flat `context_ids` column |
| "That customer's follow-up went wrong" | `find_trace.py --input-type follow_up`, `rewrite` span | Rewrite call is timed and costed on its own |
| A failure is found in production | `trace_to_case.py <id>` → fill in expectations → `run_week11_suite.py` | The skeleton is red until a human writes the expectation, so a case cannot pass by accident |
| Deploying a prompt change | canary plan in [fix_and_rollout.md](fix_and_rollout.md) | `PROMPT_VERSION` + `PROMPT_ID` pinned by a test |

## What was built

| File | What |
|---|---|
| [`backend/app/services/pricing.py`](../../backend/app/services/pricing.py) | Price table, one cost function |
| [`backend/app/services/tracing.py`](../../backend/app/services/tracing.py) | `build_spans`, schema v2 fields |
| [`backend/app/services/trace_index.py`](../../backend/app/services/trace_index.py) | SQLite + FTS5 index, rebuildable from the JSONL |
| [`backend/app/services/rag_service.py`](../../backend/app/services/rag_service.py) | Exact answer cache; `user`/`input_type` through `trace_extra`; index write; **prompt v2** |
| [`backend/app/api/chat.py`](../../backend/app/api/chat.py) | Passes the signed-in user and `X-Session-Id` into the trace |
| [`backend/app/config.py`](../../backend/app/config.py) | `TRACE_INDEX_ENABLED`, `CACHE_ENABLED`, `CACHE_TTL_SECONDS`, `CACHE_MAX_ENTRIES` |
| `backend/scripts/` | `find_trace.py`, `week11_drill.py`, `cost_report.py`, `week11_cost_experiment.py`, `run_week11_suite.py`, `trace_to_case.py` |
| [`backend/eval/week11/regression_cases.jsonl`](../../backend/eval/week11/regression_cases.jsonl) | The suite: 8 guards + F01, F02 |
| [`backend/tests/test_week11_observability.py`](../../backend/tests/test_week11_observability.py) | 16 tests, no Groq calls |

Deliberately **not** touched: `retrieve`, `_ask_inner`, `answer_with_groq` and `retrieval.py`, which `test_week5_deliverables.py` pins byte-for-byte to the Week 5 prediction commit. All Week 11 behaviour is outside them (the prompt is a module constant). The full backend suite: **243 passed before, 259 after** (16 new tests; the pinned prompt literal in `test_tracing.py` was updated for v2). The frontend is untouched; there is no Week 11 admin page.

## Findings worth reading first

1. **The planted failure was found only because `context_ids` is indexed.** "refund" is in neither the question nor the answer ([drill.md](drill.md)).
2. **My first diagnosis was wrong.** I blamed the reranker burying the refund policy (5th of 5), built a retrieval fix, measured that it changed nothing, and reverted it. The cause was the prompt ([fix_and_rollout.md](fix_and_rollout.md)). The failing prompt behaviour appears only without `temperature=0`, which is how every earlier eval ran, so none of them could have caught it.
3. **The cache saves exactly the repeat rate, and organic traffic has none.** −57.7% on a 60% repeat sequence I constructed; +0.5% (noise) on the organic one ([cost_by_stage.md](cost_by_stage.md)).
4. **36% of organic answers hit the 400-token cap and are cut off mid-sentence** (10 of 28). Found by the new logs, not fixed, and the next case for the loop.
5. **The cold-start retrieval span is 7.9 s**, 80% of the drilled request's time: the reranker loads lazily on the first `week4` request.
6. **At 10× the rate limit breaks first**: 5.5× over the 8,000 tokens/min cap at the peak minute ([tenx.md](tenx.md)).

## What is not done, plainly

- The **timed drill**. I wrote the plant script, so my own find is memory, not tooling; the squadmate protocol is in [drill.md](drill.md). `Time: __:__` is blank on purpose.
- The **bonus**.
- A **canary**: written as a plan, not shipped.
- Week-6-suite placement: the new cases are in `backend/eval/week11/`, not appended to `eval_set_25.jsonl` (reason in [fix_and_rollout.md](fix_and_rollout.md)).
- The 3,000 background traces are **synthetic**; "today's volume" in `tenx.md` is derived from them.
- The assistant (`/api/assistant`, tool-calling) path is **not traced**, so its `tools` stage cost is not measured.
- Spans are not exported to Langfuse or OpenTelemetry.

## Reproduce

```bash
cd backend
pytest                                                    # 259 passed, no Groq
TRACE_ENABLED=true uvicorn app.main:app --port 8000       # real traces -> data/traces/chat_traces.jsonl (+ trace_index.db)

python scripts/week11_drill.py seed --tz-offset 5.5       # squadmate: 3,000 synthetic requests
python scripts/week11_drill.py plant --tz-offset 5.5      # squadmate: one real v1 refund answer (calls Groq)
python scripts/find_trace.py --log data/traces/drill/chat_traces.jsonl --text refund --day yesterday --hours 12-18 --tz-offset 5.5
python scripts/find_trace.py --log data/traces/drill/chat_traces.jsonl --show <trace_id> > trace.json
python scripts/cost_report.py --log data/traces/drill/chat_traces.jsonl --trace <trace_id>

python scripts/run_week11_suite.py                        # 10 cases x 3 samples, production temperature (calls Groq, ~30 calls)
python scripts/run_week11_suite.py --no-generate          # retrieval checks only, free
python scripts/week11_cost_experiment.py --kind faq       # cache off vs on (calls Groq, ~56 calls)
python scripts/trace_to_case.py <trace_id> --id F03       # next failure -> case skeleton
```

To see RED again: put the v1 `SYSTEM_PROMPT` and `PROMPT_VERSION = "v1"` back and run the suite.
