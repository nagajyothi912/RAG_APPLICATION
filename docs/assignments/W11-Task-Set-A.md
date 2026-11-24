<!-- Soft Suave · The AI Engineering League -->
# Week 11 Practical — Task Set A

## Find the refund answer nobody logged a trace id for

| | |
|---|---|
| Domain | Customer support tickets |
| Week | 11 — Production — Observability, Cost & the Failure→Test Loop |
| Module | M6 — Production & Capstone |
| Sat on | Week 12 · Monday |
| Marks | 100 |

> **This is an extension of the app you already built in Week 11.** It is not a build from scratch, and it tests only this week's concepts. Bring your numbers written down.

## 1. Problem statement

The complaint is: "a customer said it gave a wrong answer about refunds yesterday afternoon." No trace id, no timestamp, no ticket number — that is everything you get, and it is everything you will ever get. Find it in your Week-11 logs on the clock, then close the loop so this exact failure can never ship again.

## 2. Requirements

1. A squadmate plants one bad refund answer in your logs and describes it to you only as vaguely as above. Find it from logs alone and report time-to-find in mm:ss plus which slice found it (time / user / prompt version / input type / cost outlier). Under 5 minutes, or your write-up must name the exact log field whose absence cost you the time.
2. Paste the found trace: per-span latency, tokens and cost, plus prompt version and the retrieved context ids for that request.
3. Turn the failure into an eval case, run the suite, and show it RED before the fix and GREEN after — with the suite pass counts both times (e.g. 9/10 -> 11/11), so a silent regression elsewhere cannot hide.
4. Fix at the prompt or retrieval layer, record the prompt version bump, and write a two-line canary and rollback plan for shipping it.
5. Report cost per query for that request broken down by stage (retrieval / generation / tools), then answer in one line: at 10x today's ticket volume, what breaks first — cost, latency, or a rate limit — with the number that proves it.

## 3. Expected output

drill.md (time-to-find in mm:ss + slice used), trace.json, the new eval case file, suite output RED then GREEN with pass counts, cost_by_stage.md, tenx.md (one line + number).

## 4. Evaluation rubric

| Criterion | Points |
|---|---|
| Loop closed: eval case seen RED before the fix and GREEN after, with suite pass counts both times | 30 |
| Time-to-find reported in mm:ss with the slice named, or the missing log field named honestly | 25 |
| Trace pasted with per-span latency, tokens, cost, prompt version and retrieved context ids | 20 |
| Cost per query broken down by stage and the 10x claim backed by a number | 15 |
| Prompt version bump recorded with a two-line canary and rollback plan | 10 |
| **Total** | **100** |

*Zero points for polish, UI, or "it works". Failure-finding and a number that moved are what score.*

## 5. Bonus challenge

Wire the drill shut: add the missing log field or index that would have made the find instant, have your squadmate plant a second bad answer, and beat your own time. Report both times and the one field that closed the gap.

## 6. Submission checklist

- [ ] drill.md — mm:ss, the slice that found it, timed by a named squadmate
- [ ] trace.json — per-span latency/tokens/cost + prompt version + context ids
- [ ] The eval case file, added to the Week-6 suite
- [ ] Suite output pasted twice: RED before, GREEN after, pass counts on both
- [ ] cost_by_stage.md — cost/query split by retrieval, generation, tools
- [ ] tenx.md — what breaks first at 10x, with the number

## 7. Common mistakes

- Optimising before attributing cost by stage, so you cannot say what the saving came from.
- Fixing the prompt first and adding the eval case afterwards, so you never watched it fail.
- Searching only inputs when the complaint describes the output — both have to be indexed.
- Adding the eval case, seeing it green, and not re-running the rest of the suite.
- Calling 4:59 a pass when you found it by opening the log and recognising the ticket — that is memory, not tooling.
- Blaming "the model changed" without checking the prompt version on the trace.

*Set A of 6. Sets A–F are equivalent in difficulty and objectives; only the domain differs.*
