# Week 6: Validate the ticket-reply judge before you trust its number

Support leadership is about to staff against an LLM resolution-quality score that nobody has checked
against a human. This week checks it: 26 blind hand labels, 4 deterministic assertions, a judge
measured against those labels, and one iteration driven by the judge's own disagreements.

**The short answer: the judge already agrees with us 92–96% of the time, and the iteration did not
improve it.** v2 fixed the disagreement it was shown (T017), broke one it had been getting right
(T010), and the before → after gain disappears once the judge is run more than once.

| | |
|---|---|
| `agreement_before` (judge v1, the pre-iteration run) | **92.3%** (24/26) |
| `agreement_after` (judge v2, majority of 3 runs) | **96.2%** (25/26) |
| Same method both sides (majority of 3) | v1 96.2% → v2 96.2%, **+0.0 pts** |
| Held-out 24 cases (without the two few-shot tickets) | v1 100% (24/24) → v2 95.8% (23/24) |
| Assertions vs judged criteria | **4 vs 1** |

---

## 1. Deliverables and ordering evidence

The rubric gives 0 for the blind protocol without ordering evidence, so the order is set by commits
on branch `week6-evals`:

| Commit | Time (IST) | What landed |
|---|---|---|
| `d5dacc3` | 2026-09-21 12:25:26 | [`labels_25.json`](labels_25.json) and the 26-case eval set. No judge output exists yet in the repo. |
| `13b7728` | 2026-09-21 12:31:05 | [`judge_v1.txt`](judge_v1.txt), the v1 run ([`runs/judge_v1_results.json`](../../backend/eval/week6/runs/judge_v1_results.json), which records `labels_commit: d5dacc3`), and [`prediction.txt`](prediction.txt). |
| `e9e53a2` | 2026-09-21 12:47:19 | [`judge_v2.txt`](judge_v2.txt) and the repeated v1/v2 runs. |

[`tests/test_week6_deliverables.py`](../../backend/tests/test_week6_deliverables.py) checks this order
from `git log` (labels before the v1 run, prediction before v2).

Caveat: the labels file was first written on 2026-09-17 at 12:30 IST, according to its mtime. A judge
run from that session reached Langfuse at 12:37 IST (07:07 UTC), after the labels by mtime but
before any commit. Everything above was re-run after the labels were committed, so the commit order is
the evidence. The `labeled_at` field was corrected from `12:30:00Z` to `+05:30` to match the mtime.
The labels themselves were not edited.

The files here are copies of `backend/eval/week6/`, which is what the script reads.

---

## 2. Eval set: 26 cases, each tagged with a Week 5 mode

[`eval_set_25.jsonl`](../../backend/eval/week6/eval_set_25.jsonl) has 26 cases across all five
Week 5 modes plus `no_defect_seen`. Three are **verbatim regression replays** of failed traces from
`docs/week5/traces.jsonl`: the question and the model's answer are byte-identical to the trace. A test
enforces this.

| Ticket | Trace | Mode | Failure |
|---|---|---|---|
| T012 | TR-0012 | mode_2 | Refused a plan comparison because of a mismatched doc filter |
| T055 | TR-0055 | mode_1 | Refused "how much is that?" with the fee in the top chunk |
| T112 | TR-0112 | mode_4 | Refused to confirm that a 2024 legacy plan is still valid |

T035 was flagged as a regression before, but its reply is not the TR-0035 answer, so the flag is off.
It is still a mode_5 case.

---

## 3. Assertion / judge split

Four criteria moved out of the judge into `if` statements in
[`evaluate_week6.py`](../../backend/scripts/evaluate_week6.py). Judge v1's prompt tells the judge not
to check them:

| Assertion | Rule | Result |
|---|---|---|
| `ticket_id_echoed` | Ticket ID appears in the reply | 26/26 |
| `refund_amount_numeric` | If a refund is promised, a ₹ amount is stated | 25/26 (T016) |
| `priority_escalation` | Priority tier → escalation marker present | 26/26 |
| `no_refund_outside_30_days` | Tenure > 30 days and refund requested → no full refund promised | 26/26 |

That leaves **one judged criterion**: binary resolution quality (PASS = 1 / FAIL = 0).

T016's failure is a **false positive in the assertion**, not in the reply. The customer asked what the
refund *conditions* are, and the reply restates them ("eligible for a full refund of plan charges
within the first 30 days…"). No amount is being promised, and the policy states none. The rule fires
on the words "eligible for" + "refund". It should only apply when a specific refund is being granted.
The hand label (PASS) is right.

---

## 4. Pass rate by Week 5 mode

Output of `.venv/bin/python scripts/evaluate_week6.py` (full transcript in
[`runs/full_run.txt`](../../backend/eval/week6/runs/full_run.txt)):

```
Week 5 Mode      | Cases | Assertions |  Human |  Judge v1 |  Judge v2
--------------------------------------------------------------------------------
mode_1           |     3 |       100% |     0% |        0% |        0%
mode_2           |     2 |       100% |     0% |        0% |        0%
mode_3           |     2 |       100% |   100% |      100% |      100%
mode_4           |     2 |       100% |     0% |        0% |        0%
mode_5           |     1 |       100% |     0% |        0% |        0%
no_defect_seen   |    16 |        94% |   100% |       94% |       94%
--------------------------------------------------------------------------------
OVERALL          |    26 |        96% |    69% |       65% |       65%
```

The judge and the human agree completely on every defect mode. All the disagreement sits in
`no_defect_seen`: replies a human reads as fine, where the judge objects to a detail. The overall 65%
also hides that modes 1, 2, 4 and 5 are 0% passes. The average is carried by the 16 clean cases.

---

## 5. Agreement before → after

The judge (`openai/gpt-oss-120b` on Groq, temperature 0) is **not deterministic**. One flipped verdict
moves agreement by 3.8 points on 26 cases, so the script now runs each judge 3 times (`--repeats`) and
reports the majority vote plus every run:

| Run | Commit | Agreement | Disagreements |
|---|---|---|---|
| v1, pre-iteration (1 run) | `13b7728` | 24/26 = **92.3%** | T017, T022 |
| v1, repeated (3 runs) | `e9e53a2` | 25, 25, 25 of 26 | T017 |
| v2, repeated (3 runs) | `e9e53a2` | 25, 24, 24 of 26 | T010 (3/3), T119 (1/3) |

v2 is v1 plus the two pre-iteration disagreements as few-shot examples (with the human label), plus one
sentence: *grade the core answer; small wording drift in a secondary detail is not a FAIL.* The diff is
`diff judge_v1.txt judge_v2.txt`.

**Reading:** `92.3% → 96.2%` is the number the protocol produces, but it isn't a real improvement.
The 92.3% came from a single v1 run where T022 happened to flip. T022 disagreed in 1 of 4 v1 runs.
Measured the same way on both sides, agreement is flat, and on the 24 cases v2 didn't see as examples
it went **down** (24/24 → 23/24). The v2 score on T017 and T022 is also partly leakage, because those
answers are in its prompt.

---

## 6. Disagreements: who was right

| Ticket | Human | Judge | Who was right |
|---|---|---|---|
| **T017** (v1) | PASS | FAIL, 4/4 v1 runs | **Judge.** The reply says the supervisor "will finalize this within 24 hours"; policy says the refund is processed in 5–7 business days. The customer is on their third contact, and a 24-hour promise that can't be kept buys a fourth. We labelled PASS because the core yes/₹1999 answer was right; the judge caught a false commitment we skimmed past. |
| **T022** (v1) | PASS | FAIL, 1/4 v1 runs | **Human.** All four parts are answered correctly. "Within 7 business days following inspection" drifts from "7 days of device receipt", but the drift is toward a later date, so it can't create a broken promise. The judge's objection was also unstable. |
| **T010** (v2) | PASS | FAIL, 3/3 v2 runs (v1: PASS, 3/3) | **Human.** The customer asks for "the timeline" of their stalled move. The context has no completion date for their case, only the 3–5 day standard, so the reply gives that, the ₹100/day credit and an escalation. v2 fails it for not answering something the context can't answer. |

The T017 row is the uncomfortable one. v2 "fixed" T017 by being shown our PASS label, which taught the
judge to wave through an invented timeline. That's a case where agreement went up and the judge got
worse. The label was not changed: relabelling to win agreement moves the ruler, and a wrong label is
something to argue about in writing, not quietly edit.

---

## 7. Prediction, scored

Filed in `13b7728` before `judge_v2.txt` existed:

> *Showing the judge T017 and T022 as PASS examples will fix both disagreements without breaking any
> of the 24 cases v1 already agrees on, because the judge will learn to grade the core answer and
> ignore small wording drift in timelines.*

- **Right:** T017 and T022 both agree with the human in every v2 run.
- **Wrong about "without breaking any":** T010 broke in all 3 v2 runs, and T119 in 1 of 3.
- **Wrong about the mechanism:** the judge didn't just learn to ignore drift. The line "if every part
  of the question is answered correctly" made it *stricter* about completeness. T010 and T119 both
  fail for "does not answer part of the question". The calibration sentence moved the judge in two
  directions at once, and the prediction only foresaw one.

The next iteration would drop that sentence and keep only the examples. Removing a sentence rather than
adding more examples is the cheaper test of which change did the damage.

---

## 8. Langfuse

The full run (`--judge both`) writes all 26 cases to the
[Langfuse project](https://us.cloud.langfuse.com/project/cmts8l4k00513ad0g86x36tlp): one trace per
ticket (tags `week6`, `mode:*`, `tier:*`, `regression`), the dataset `week6_ticket_replies`, and the
scores `human_ground_truth`, `assertions_passed`, `judge_v1_score`, `judge_v2_score`,
`judge_v1_agreement` and `judge_v2_agreement`.

Traces land in the `development` environment (the default of `LANGFUSE_ENVIRONMENT`). The Home
dashboard defaults to `default` and to the past day, so set **Env → development** and widen the time
range to see them. Trace ids are seeded from the ticket id, so re-runs update the same traces.

---

## 9. Bonus (RAGAS): not attempted

Not done this week. An earlier draft of this README quoted faithfulness 0.98 / 0.94 figures; those
were never computed and have been removed.

---

## 10. Run it

```bash
cd backend
.venv/bin/python scripts/evaluate_week6.py                    # assertions, v1 + v2 x3, table, Langfuse
.venv/bin/python scripts/evaluate_week6.py --judge v1 --repeats 1 --no-langfuse   # pre-iteration run only
.venv/bin/pytest tests/test_week6_deliverables.py -v
```
