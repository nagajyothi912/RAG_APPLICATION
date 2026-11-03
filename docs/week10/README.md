# Week 10 — Task Set A submission: race the triage squad against the single agent

Brief: [../assignments/W10-Task-Set-A.md](../assignments/W10-Task-Set-A.md). Code: [backend/app/services/triage_squad/](../../backend/app/services/triage_squad/).

## Checklist

| Deliverable | File | Headline |
| --- | --- | --- |
| `race_table.md`: 4 metrics × 2 arms, same 10 cases named | [race_table.md](race_table.md) | Squad vs single: pass **8/10 vs 7/10**, p50 **4.3 s vs 5.0 s**, p99 **7.5 s vs 18.4 s**, tokens **32,874 vs 53,462**, cost/ticket **$0.000875 vs $0.001191** |
| `handoffs.log`: every hand-off with its token count | [handoffs.log](handoffs.log) | One line per LLM call and per failed hand-off, with per-hand-off totals; single-agent calls at the end for comparison |
| Multiplier line with the dominant hand-off | [race_table.md#multiplier](race_table.md#multiplier) | **0.6x** as counted (~0.8x with Groq-rejected calls estimated). Largest share: **"orchestrator -> triage worker", 43%** of squad tokens |
| `failure_case.md`: the injected 500 and what happened | [failure_case.md](failure_case.md) | **Retried once, then degraded.** Didn't lie, but the reply was cut off mid-sentence and said $1,999 instead of ₹ |
| `verdict.md`: keep/kill, two numbers, sunk cost named | [verdict.md](verdict.md) | **Keep, conditionally**, over the Week 7 single agent; not shown to beat the Week 7 fixed workflow |
| Bonus: AgentCard + A2A lifecycle | [agent_card.json](agent_card.json), [a2a_lifecycle.md](a2a_lifecycle.md) | The failed case should pause in `input-required` for the ticket owner, not end `failed` |

Raw results: [eval/week10/race_results.json](../../eval/week10/race_results.json).

**In the app:** admin console → Labs → **Week 10** (`#week10`), served read-only by `GET /api/week10/report`. Its numbers come from the same functions as `race_table.md` (`triage_squad/report.py`), so the two cannot disagree. There is no run button on purpose: a run costs ~115k Groq tokens, and a button makes "re-run the squad until it wins" one click away.

## The two arms

| | Single agent | Triage squad |
| --- | --- | --- |
| Code | Week 7 `ticket_reply_app/agent.py`, unchanged (baseline prompt) | `triage_squad/orchestrator.py` + `workers.py`, workers behind HTTP (`worker_api.py`) |
| LLM steps | One ReAct loop over all 4 tools, then `generate_ticket_reply` | decompose → triage worker ∥ policy worker → `generate_ticket_reply` |
| Tools | `retrieve_kb_context`, `lookup_order_record`, `escalate_ticket`, `generate_ticket_reply` | triage: `lookup_order_record`, `escalate_ticket`; policy: `retrieve_kb_context` only |
| Context | The whole conversation, re-sent every turn | Triage gets ticket metadata + a one-line brief; policy gets a query + the question; neither sees the other's data |

## How the race was kept fair

- **Same cases.** The 10 Week 7 ticket ids, read from the Week-6 eval set `backend/eval/week6/eval_set_25.jsonl`. Week 7's copy in `tickets.py` lists T010 at `tenure_days=0`, where the eval set says 42; the race uses the eval set.
- **Same judge.** The Week 6 `judge_v2.txt`, imported from `scripts/evaluate_week6.py`, plus the four Week 6 assertions. A case passes only if both pass. One judge vote per reply (Week 6 used three) to save quota.
- **Same model and retrieval.** `openai/gpt-oss-120b`, temperature 0, the same mock KB, the same reply-writing tool.
- **Same metering.** Both arms run through one `MeteredClient`, so every LLM call is counted, including the call inside `generate_ticket_reply` that Week 7's agent total left out. It also records time spent waiting on Groq 429s; this run had none.
- **Arm order alternates per case**, with a 20 s pause between runs so one arm doesn't drain the next one's per-minute quota.
- The Week 7 agent's 60 s wall-clock budget was raised to 600 s so quota waits couldn't end its runs; its other three budgets are unchanged.

## Disclosed: one aborted run

The first attempt was stopped after 5 runs (kept in [eval/week10/aborted_run1/](../../eval/week10/aborted_run1/)). On T119, gpt-oss emitted a worker's final JSON as a call to a non-existent tool called `json`, Groq rejected the turn with a 400, and the worker returned a real 500 twice. That was a bug in my worker, not the pattern under test, so I fixed it (`recover_final_answer` in `workers.py`, with tests) and re-ran **both arms from scratch** rather than only the squad. In the scored run the same quirk happened 10 times inside the squad and was recovered each time. Groq reports no usage for rejected calls, so the table shows the squad's tokens both as counted and with an estimate.

## What this does not show

- n=10 and one judge vote: the one-case pass-rate gap is noise. The token, cost and p99 gaps are large enough to be real.
- p99 of 10 values is the slowest ticket.
- The squad is not compared against the Week 7 fixed workflow (about 5k tokens on these tickets), which is probably still the cheapest design.
- Pricing is $0.15/M input and $0.60/M output from public trackers; Groq's launch post said $0.75 output. Both arms use the same constants, so the multiplier doesn't depend on them.

## Reproduce

```bash
cd backend
python -m app.services.triage_squad.race               # resumes from eval/week10/race_results.json if present
python -m app.services.triage_squad.race --fresh       # start over (calls Groq: ~115k tokens incl. judge)
python -m app.services.triage_squad.race --report-only # rebuild race_table.md, handoffs.log, failure_case.md
pytest tests/test_week10_squad.py -v                   # no Groq calls
```

`race_table.md`, `handoffs.log` and the top half of `failure_case.md` are generated. The confirmed behaviour in `failure_case.md` (below `<!-- confirmed -->`), `verdict.md` and `a2a_lifecycle.md` are hand-written.
