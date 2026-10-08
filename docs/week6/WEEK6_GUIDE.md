# Week 6 — Can we trust an LLM to grade our support replies?

> **TL;DR.** The plan was to grade support-ticket replies with an AI model (an "LLM judge") instead of a person. Before anyone relied on that score, this week checked it against a human. 26 replies were labelled PASS/FAIL by hand, and the labels were committed to git **before** the judge ever ran. Four checks that plain code can do were moved out of the judge. The judge (v1) was then compared with the human labels, and one improvement round (v2) was built from v1's own mistakes. Result: the judge already agreed with the human **92–96%** of the time, and **the improvement round did not really help**. The headline 92.3% → 96.2% gain disappears once both versions are run 3 times and measured the same way (96.2% → 96.2%, +0.0 points). On the 24 cases v2 had not seen as examples, agreement went *down* (24/24 → 23/24). The official graded write-up is [README.md](README.md). This guide explains it from scratch.

---

## 1. The problem in plain words

The project is "Ask My Documents", a RAG app for a mock broadband company called AirFiber. RAG means retrieval-augmented generation: the app looks up help-centre articles and has an LLM write an answer from them. In Week 5 we read real traces by hand and found 5 ways the app fails (see [../week5-6-summary.md](../week5-6-summary.md)). For example, it sometimes refuses to answer even though the answer was retrieved.

Reading every reply by hand doesn't scale. The obvious shortcut is an **LLM-as-judge**: a second LLM reads the customer question, the reference context and the drafted reply, then says PASS or FAIL. The README frames the stakes this way: support leadership is about to staff against this score, and nobody has checked it against a human.

So the question for Week 6 is: **does the judge's verdict match what a careful human would say, and can we make it match better?** Answering that honestly takes some discipline:

- The human labels must be written **without seeing the judge's answers** (blind). Otherwise the human might be nudged by the judge.
- Anything a simple rule can check (for example "does the reply include the ticket ID?") should be checked by code, not by an LLM.
- If we change the judge prompt to fix its mistakes, we must check that the fix generalises. It shouldn't only memorise the examples we showed it.
- We must write down what we expect to happen **before** the change, so we can't rewrite our expectations afterwards.

---

## 2. Requirements

> **Note:** There is **no Week 6 assignment file** in `docs/assignments/` (only `W3-Task-Set-A.md` and `W4-Task-Set-A.md` exist). The requirements below are reconstructed from three sources: the rubric points listed in the docstring of [`test_week6_deliverables.py`](../../backend/tests/test_week6_deliverables.py), the rubric references in [README.md](README.md) (for example "the rubric gives 0 for the blind protocol without ordering evidence"), and the commit messages.

| # | Requirement (reconstructed) | Status | Where |
|---|---|---|---|
| 1 | Eval set of 25+ cases, each tagged with a Week 5 failure mode | ✅ 26 cases, all 5 modes + `no_defect_seen` | [eval_set_25.jsonl](../../backend/eval/week6/eval_set_25.jsonl) |
| 2 | Include real regression cases taken from failed traces | ✅ 3 verbatim replays (T012, T055, T112), checked by a test | [eval_set_25.jsonl](../../backend/eval/week6/eval_set_25.jsonl), [test](../../backend/tests/test_week6_deliverables.py) |
| 3 | Blind hand labels for every case | ✅ 26 labels (18 PASS / 8 FAIL) | [labels_25.json](labels_25.json) |
| 4 | Ordering evidence: labels provably exist before any judge run | ✅ commit `d5dacc3` (labels) before `13b7728` (v1 run), checked by a test. ⚠️ The file was first written on 2026-09-17, and one judge run reached Langfuse before the commit (disclosed in README §1) | [README.md §1](README.md), [test](../../backend/tests/test_week6_deliverables.py) |
| 5 | Move at least 2 criteria from the judge into deterministic assertions, and remove them from the judge prompt | ✅ 4 assertions, 1 judged criterion. ⚠️ One assertion has a known false positive (T016) | [evaluate_week6.py](../../backend/scripts/evaluate_week6.py), [judge_v1.txt](judge_v1.txt) |
| 6 | Measure `agreement_before` → `agreement_after` | ✅ 92.3% → 96.2% (protocol number), +0.0 pts like-for-like | [README.md §5](README.md), [runs/](../../backend/eval/week6/runs/) |
| 7 | Iteration driven by the judge's **own** disagreements | ✅ v2's few-shot examples are exactly v1's disagreements T017 and T022, checked by a test | [judge_v2.txt](judge_v2.txt) |
| 8 | Read at least 2 disagreements and give a verdict on who was right | ✅ 3 analysed (T017 → judge right; T022, T010 → human right) | [README.md §6](README.md) |
| 9 | A written prediction committed before v2, then scored | ✅ committed in `13b7728`, before `judge_v2.txt` (`e9e53a2`). Scored as partly right | [prediction.txt](prediction.txt), [README.md §7](README.md) |
| 10 | Eval runs in one command | ✅ `python scripts/evaluate_week6.py` | [evaluate_week6.py](../../backend/scripts/evaluate_week6.py) |
| 11 | Pass rate broken down by Week 5 mode | ✅ table per mode for assertions, human, v1 and v2 | [README.md §4](README.md), [full_run.txt](../../backend/eval/week6/runs/full_run.txt) |
| 12 | Log to Langfuse (traces, scores, judge calls) | ✅ one trace per ticket, judge calls logged as generations, 6 scores. ⚠️ Cost shows empty (no price set for the model) | [README.md §8](README.md) |
| 13 | Bonus: RAGAS metrics | ❌ not attempted (README §9) | [README.md §9](README.md) |

---

## 3. Concepts covered

**LLM-as-judge.** Using an LLM to grade another LLM's output. *Why:* it is much cheaper and faster than a human reading every reply. *Catch:* the judge is itself an LLM, so it can be wrong or inconsistent, and you have to measure how often. *Where:* `call_llm_judge()` in [evaluate_week6.py](../../backend/scripts/evaluate_week6.py) sends the judge prompt plus context, question and reply to `openai/gpt-oss-120b` on Groq and parses a JSON `{"score": 0|1, "explanation": ...}`. If the judge returns something that can't be parsed, the case is flagged as an error rather than silently counted as FAIL.

**Binary criterion.** The judge answers one yes/no question, *resolution quality*: did the reply correctly and helpfully answer the customer from the context? PASS = 1, FAIL = 0. Binary is easier to agree on than a 1–10 scale.

**Blind labelling / ground truth.** A human labels every case *before* seeing any judge output. These labels are the "ground truth" the judge is measured against. *Why blind:* if you see the judge's verdict first, you tend to agree with it, and the measurement becomes circular. *Where:* [labels_25.json](labels_25.json). Each label has `label` (0/1), `verdict` and a written `reason`.

**Ordering evidence.** You can't *prove* a label was blind, but you can prove it existed before the judge output. Git commit order does that. *Where:* commits `d5dacc3` → `13b7728` → `e9e53a2`. Every saved judge run also records `labels_commit`, and two tests re-check the order from `git log`.

**Deterministic assertion.** A plain `if` check in code that always gives the same answer for the same input, for example "the ticket ID appears in the reply". *Why:* it is free, instant and never "changes its mind". Only judgement calls should go to the LLM. *Where:* the four `assert_*` functions and the `ASSERTIONS` dict in [evaluate_week6.py](../../backend/scripts/evaluate_week6.py). [judge_v1.txt](judge_v1.txt) explicitly tells the judge **not** to check them.

**Agreement rate.** The share of cases where the judge's verdict equals the human label. 24 of 26 = 92.3%. With only 26 cases, **one case = 3.8 percentage points**, so small differences are noise.

**`agreement_before` → `agreement_after`.** Agreement for the original judge (v1) versus the improved judge (v2). This is the number the protocol asks for. The point of this week is that it can mislead you.

**Few-shot prompting.** Putting a few worked examples (input + correct answer) in the prompt so the model copies the pattern. "Zero-shot" means no examples. v1 is zero-shot; v2 adds 2 examples. *Where:* the `FEW-SHOT CALIBRATION EXAMPLES` block in [judge_v2.txt](judge_v2.txt).

**Iterating from disagreements.** The examples in v2 are not hand-picked favourites. They are exactly the cases where v1 disagreed with the human (T017, T022), and they carry the human's label, not a new one. A test enforces both rules.

**Held-out set.** Cases the judge has *not* seen as examples. *Why:* v2 has T017 and T022 (with their answers) in its prompt, so getting them "right" is partly copying. This is called **leakage**. Agreement on the other 24 cases is the honest measure of whether v2 got better. *Where:* the "held-out" lines printed by the script, which read the example IDs out of `judge_v2.txt`.

**Overfitting to examples.** Changing a prompt so it fixes the cases you looked at but gets worse on cases you didn't look at. This happened here: v2 fixed T017 but broke T010.

**Non-determinism.** Even at temperature 0 (the setting meant to make output repeatable), the judge sometimes gives a different verdict for the same input. In the committed runs, T022 flipped in 1 of 4 v1 runs, T119 in 1 of 3 v2 runs, and T035 in 1 of 3 v2 runs.

**Majority vote (majority of 3).** Run the judge 3 times per case and take the verdict that appears at least twice. This smooths out random flips. *Where:* the `--repeats` flag (default 3) in `main()`. Each saved run stores every vote.

**Prediction before the change.** One sentence, committed before v2 existed, saying what v2 would do. Afterwards it is scored as right or wrong. *Why:* it stops you from explaining away results after the fact. *Where:* [prediction.txt](prediction.txt).

**Regression case.** A test case copied byte-for-byte from a real failure (a Week 5 trace), so a future fix can be checked against the exact failure. *Where:* rows with `"is_regression": true` in the eval set. `test_regression_cases_are_verbatim_trace_replays` checks them against `docs/week5/traces.jsonl`.

**Langfuse.** A hosted dashboard for LLM traces. A *trace* is one unit of work, a *span* is a step inside it, a *generation* is a span that is an LLM call (with model, prompt, output and tokens), and a *score* is a number attached to a trace. *Where:* `log_to_langfuse()` in [evaluate_week6.py](../../backend/scripts/evaluate_week6.py).

---

## 4. What was implemented

```text
 Week 5 traces (docs/week5/traces.jsonl)
          │  3 failed traces copied verbatim (T012, T055, T112)
          ▼
 eval_set_25.jsonl  (26 cases, each tagged mode_1..mode_5 / no_defect_seen)
          │
          ├──► labels_25.json  (blind human PASS/FAIL)  ── commit d5dacc3 ── FIRST
          │
          ▼
 scripts/evaluate_week6.py
   STEP 1  4 deterministic assertions (plain Python, no LLM)
   STEP 2  judge v1 (judge_v1.txt, zero-shot)      ──┐  each run x3,
   STEP 3  judge v2 (judge_v2.txt, few-shot)       ──┘  majority vote
   STEP 4  pass rate per Week 5 mode table
   STEP 5  agreement_before / agreement_after / held-out
   STEP 6  disagreements, "fixed by v2" / "broken by v2"
   STEP 7  prints prediction.txt
          │
          ├──► eval/week6/runs/judge_<v>_<timestamp>.json  (votes, prompt sha256, labels commit)
          └──► Langfuse: session per run, trace per ticket,
               span + 2 generations (judge_v1, judge_v2) + 6 scores + tags

 tests/test_week6_deliverables.py  re-checks case count, mode tags, labels,
 assertions, few-shot rules, verbatim regressions, and git commit ORDER.
```

**The pieces**

| Piece | What it is |
|---|---|
| Eval set | 26 JSON lines. Each has `ticket_id`, `week5_mode`, `tier` (Standard/Priority), `tenure_days`, `refund_requested`, `question`, `context`, `drafted_reply`, and optionally `trace_id`/`is_regression`. Mode counts: `no_defect_seen` 16, `mode_1` 3, `mode_2` 2, `mode_3` 2, `mode_4` 2, `mode_5` 1. The file is named `_25` but holds 26 cases. |
| Labels | 26 binary labels with reasons; metadata says protocol `blind_human_evaluation`, 18 PASS / 8 FAIL. |
| 4 assertions | `ticket_id_echoed`, `refund_amount_numeric` (if a refund is promised, a ₹ amount is stated), `priority_escalation` (Priority tier → escalation words present), `no_refund_outside_30_days` (tenure > 30 days and refund requested → no "100% refund"/"full refund of"). |
| Judge v1 | Zero-shot prompt with a single criterion and a scope note listing what *not* to check. |
| Judge v2 | v1 + one calibration sentence ("Grade the core answer… small wording drift in a secondary detail… is not by itself a FAIL") + T017 and T022 as examples labelled PASS. Run `diff judge_v1.txt judge_v2.txt` to see the change. |
| Prediction | One sentence in `prediction.txt`, committed with the v1 run. |
| Saved runs | `judge_v1_results.json` is the single pre-iteration run. `judge_v1_20260921T070956Z.json` and `judge_v2_20260921T071637Z.json` are the majority-of-3 runs. `v1_run.txt` and `full_run.txt` are the console transcripts. |
| Langfuse logging | Added in `13b7728`/`e9e53a2`, upgraded in `84718ec` (judge calls as generations, tags actually applied, one session per run). `2d487b3` added the `--replay` mode and the Week 5-compatible mode tags (`mode:1`, `no-defect-seen`). |
| Tests | 11 tests in `backend/tests/test_week6_deliverables.py`. |

**Commit timeline** (all on branch `week6-evals`, times IST)

| Commit | When | What |
|---|---|---|
| `d5dacc3` | 2026-09-21 12:25 | Labels + eval set. No judge output exists yet. |
| `13b7728` | 12:31 | `judge_v1.txt`, the pre-iteration v1 run (records `labels_commit: d5dacc3`), `prediction.txt`, the script. |
| `e9e53a2` | 12:47 | `judge_v2.txt`, the repeated v1/v2 runs, the ordering tests. |
| `2166f6f` | 12:48 | README rewritten from the committed runs. Earlier numbers that matched no run, and RAGAS figures that were never computed, were removed. |
| `84718ec` | 12:55 | Judge calls logged to Langfuse as generations; tags actually attached. |
| `2d487b3` | 2026-09-28 | `--replay` to Langfuse, mode-tag spelling fix, [week5-6-summary.md](../week5-6-summary.md). |

---

## 5. Analysis & results

### Headline numbers

| Measurement | v1 | v2 |
|---|---|---|
| Protocol number: v1 single run → v2 majority of 3 | 92.3% (24/26) | 96.2% (25/26) |
| Same method both sides (majority of 3) | 96.2% (25/26) | 96.2% (25/26) → **+0.0 pts** |
| Per-run agreement (3 runs each) | 25, 25, 25 | 25, 24, 24 |
| Held-out 24 cases (without T017, T022) | 100% (24/24) | **95.8% (23/24)** |
| Disagreements (majority) | T017 | T010 (3/3 runs); T119 flipped in 1/3 |
| Assertions vs judged criteria | 4 vs 1 | |

The pre-iteration v1 run disagreed on **T017** and **T022**, both human PASS / judge FAIL.

### Assertions

`ticket_id_echoed` 26/26, `refund_amount_numeric` 25/26 (fails on T016), `priority_escalation` 26/26, `no_refund_outside_30_days` 26/26. The T016 failure is a **false positive in the rule**, not a bad reply. The customer asked what the refund *conditions* are, and the reply restates them. The rule fires on "eligible for" + "refund" even though no specific refund is being granted.

### Pass rate by Week 5 mode (from `full_run.txt`)

| Mode | Cases | Assertions | Human | Judge v1 | Judge v2 |
|---|---|---|---|---|---|
| mode_1 | 3 | 100% | 0% | 0% | 0% |
| mode_2 | 2 | 100% | 0% | 0% | 0% |
| mode_3 | 2 | 100% | 100% | 100% | 100% |
| mode_4 | 2 | 100% | 0% | 0% | 0% |
| mode_5 | 1 | 100% | 0% | 0% | 0% |
| no_defect_seen | 16 | 94% | 100% | 94% | 94% |
| **Overall** | 26 | 96% | 69% | 65% | 65% |

What it means:
- The judge and the human **agree completely on every defect mode**. Every disagreement is on a reply the human considered fine.
- Mode 3 (an odd citation bracket style, a cosmetic defect) passes at 100%. That makes sense: the reply still resolves the question, and a cosmetic issue isn't what "resolution quality" measures.
- The overall 65–69% hides that modes 1, 2, 4 and 5 pass **0%** of the time. The 16 clean cases carry the average.

### The disagreements, and who was right (details in [README §6](README.md))

- **T017. The judge was right; the human label was wrong.** The reply promises the supervisor "will finalize this within 24 hours", but the policy says 5–7 business days. The human labelled PASS because the core answer (yes, ₹1999 refund) was right. v2 "fixed" this disagreement by being shown the PASS label, which taught it to accept an invented timeline. **Agreement went up while the judge got worse.** The label was deliberately *not* changed, because editing labels to win agreement moves the ruler.
- **T022. The human was right.** All four parts are answered; the deposit-timing wording drifts toward a *later* date, which can't create a broken promise. The judge objected in only 1 of 4 v1 runs.
- **T010. The human was right; v2 broke this case.** The customer asks for "the timeline". The context has no completion date for this specific case, so the reply gives the standard 3–5 days, the ₹100/day credit and an escalation. v2 failed it in 3/3 runs for not answering something the context can't answer. v1 passed it 3/3.

### The prediction, scored ([README §7](README.md))

The prediction said: *"showing T017 and T022 as PASS examples will fix both disagreements without breaking any of the 24 cases v1 already agrees on…"*

- **Right:** T017 and T022 agree with the human in every v2 run.
- **Wrong:** T010 broke (3/3) and T119 flipped (1/3).
- **Wrong about why:** the calibration sentence also contains "if every part of the question is answered correctly", and that made the judge **stricter** about completeness. Both T010 and T119 failed for "does not answer part of the question". One sentence pushed the judge in two directions at once.

### The honest conclusion

**The iteration did not improve the judge.** Three reasons:

1. **Unequal measurement.** The 92.3% "before" figure is a single run in which T022 happened to flip. The 96.2% "after" figure is a majority of 3. Measure both as a majority of 3 and they are equal (96.2% vs 96.2%).
2. **Leakage.** v2 has the answers to T017 and T022 in its prompt, so getting them right proves little. On the 24 held-out cases v2 is *worse* (23/24 vs 24/24).
3. **Agreement isn't the same as correctness.** On T017, higher agreement meant accepting a reply that makes a promise the company can't keep.

The useful findings are about method. Run the judge more than once. Report held-out agreement. Read disagreements before trusting a percentage. The README's suggested next step is a v3 that **removes** the calibration sentence and keeps only the examples, to find out which change caused the damage.

---

## 6. What is NOT implemented / limitations / known gaps

- **RAGAS bonus: not attempted.** An earlier README draft quoted faithfulness figures that were never computed. They were removed in `2166f6f`.
- **No judge v3.** The proposed experiment (drop the calibration sentence) is listed as an open item in [../week5-6-summary.md](../week5-6-summary.md) and was not run.
- **`refund_amount_numeric` false positive (T016)** is documented but not fixed.
- **Small sample.** 26 cases, and only 1–3 cases per defect mode, so one flip = 3.8 points. Per-mode percentages for modes 1–5 rest on 1–3 cases each.
- **Single human labeller, and one label is arguably wrong** (T017). There is no second labeller and no inter-annotator agreement, so the "ground truth" is one person's view.
- **Blindness is evidenced by commit order, not proven absolutely.** The labels file was first written on 2026-09-17 (by mtime). A judge run from that session reached Langfuse before any commit, but after the labels by mtime. `labeled_at` was corrected from a `Z` (UTC) suffix to `+05:30`; the labels themselves were not edited. Everything reported was re-run after the labels commit (README §1 and the `d5dacc3` commit message).
- **Transcript oddity.** The pre-iteration console transcript [`v1_run.txt`](../../backend/eval/week6/runs/v1_run.txt) prints a *different, older* prediction sentence and shows `prediction.txt` as "uncommitted" at run time. The committed [prediction.txt](prediction.txt) is the T017/T022 sentence. The requirement (prediction committed before v2) still holds and is test-checked. The prediction was *not* written before v1 ran, and it doesn't have to be.
- **Non-determinism at temperature 0.** Re-running the script will not reproduce exactly the same votes. The committed run files are the evidence; `--replay` re-shows them in Langfuse without calling the judge.
- **Langfuse gaps.** Cost shows empty because Langfuse has no price for `openai/gpt-oss-120b`. The runs committed in `e9e53a2` were synced before generation logging existed (use `--replay` to view them properly). Replayed generations carry no raw output or token usage. 2 stale test traces still carry an old tag (open item in the summary).
- **Assertions are keyword rules.** For example, `priority_escalation` accepts words like "senior" or "supervisor" anywhere in the reply. They are cheap and repeatable, but shallow.
- **Judge sees only the given context.** It grades against the `context` field in the eval set, not the live knowledge base.
- **No automatic grading of live traffic.** Running assertions and the judge on new traces is an open item.

---

## 7. How to run & verify

All commands run from `backend/` (see the repo's `CLAUDE.md` for venv setup; you need `GROQ_API_KEY` in `backend/.env`).

> ⚠️ **The eval script calls Groq** (`openai/gpt-oss-120b`), which costs API quota. With defaults it makes 26 cases × 2 judges × 3 repeats = **156 judge calls**. It also writes new timestamped files into `backend/eval/week6/runs/` on every run, and syncs to Langfuse if Langfuse keys are configured. Results will vary slightly from the committed ones because the judge is not deterministic.

```bash
cd backend

# Cheapest check: no LLM calls, no network. 11 tests (case count, tags, labels,
# assertions, few-shot rules, verbatim regressions, git commit ordering).
.venv/bin/pytest tests/test_week6_deliverables.py -v

# Full run: assertions, v1 x3, v2 x3, tables, agreement, disagreements, Langfuse sync
.venv/bin/python scripts/evaluate_week6.py

# Same, without Langfuse
.venv/bin/python scripts/evaluate_week6.py --no-langfuse

# Quick smoke test on the first 5 cases only, no Langfuse
.venv/bin/python scripts/evaluate_week6.py --limit 5 --repeats 1 --no-langfuse

# Reproduce the pre-iteration protocol (v1 only, single run)
.venv/bin/python scripts/evaluate_week6.py --judge v1 --repeats 1 --no-langfuse

# Show the COMMITTED runs in Langfuse without calling the judge (needs Langfuse keys)
.venv/bin/python scripts/evaluate_week6.py --replay \
  eval/week6/runs/judge_v1_20260921T070956Z.json eval/week6/runs/judge_v2_20260921T071637Z.json
```

Flags: `--judge v1|v2|both` (default `both`), `--repeats N` (default 3), `--limit N`, `--no-langfuse`, `--model`, `--eval-set`, `--labels`, `--replay V1_RUN V2_RUN`. Langfuse sync only happens for `--judge both`. The script refuses to run if any case lacks a hand label. `--replay` refuses if the prompt file has changed since the run was saved (sha256 check).

**What you see.** The console output matches [`full_run.txt`](../../backend/eval/week6/runs/full_run.txt):
1. The loaded case count, the 3 regression IDs, and the labels commit (`d5dacc3`).
2. STEP 1: each assertion's pass count, plus `T016 fails: refund_amount_numeric`.
3. STEP 2/3: one line per ticket with `judge=`, `votes=[…]`, `human=`, `XX` for a disagreement and `(unstable)` when votes differ.
4. The pass-rate-by-mode table.
5. `agreement_before`, `agreement_after`, delta, held-out agreement for both judges, and `assertions vs judged criteria : 4 vs 1`.
6. The disagreement list with human vs judge reasons, then `fixed by v2` / `broken by v2`.
7. The prediction text and its commit.

**To verify the evidence without running the judge:**
```bash
git log --format='%h %ad %s' --date=iso d5dacc3 -1
git log --format='%h %ad %s' --date=iso 13b7728 -1
git log --format='%h %ad %s' --date=iso e9e53a2 -1
diff docs/week6/judge_v1.txt docs/week6/judge_v2.txt
```

---

## 8. Files for this week

| File | Role |
|---|---|
| [README.md](README.md) | **The graded write-up.** Hand-written; must not be regenerated. |
| [judge_v1.txt](judge_v1.txt) / [judge_v2.txt](judge_v2.txt) | Judge prompts (copies of `backend/eval/week6/`). |
| [labels_25.json](labels_25.json) | Blind human labels (copy). |
| [prediction.txt](prediction.txt) | The one-sentence prediction (copy). |
| [../../backend/eval/week6/eval_set_25.jsonl](../../backend/eval/week6/eval_set_25.jsonl) | The 26 mode-tagged cases. |
| [../../backend/eval/week6/](../../backend/eval/week6/) | The originals the script actually reads (labels, prompts, prediction). |
| [../../backend/eval/week6/runs/judge_v1_results.json](../../backend/eval/week6/runs/judge_v1_results.json) | Pre-iteration v1 run (24/26), records `labels_commit`. |
| [../../backend/eval/week6/runs/judge_v1_20260921T070956Z.json](../../backend/eval/week6/runs/judge_v1_20260921T070956Z.json) | v1 majority-of-3 run (25, 25, 25). |
| [../../backend/eval/week6/runs/judge_v2_20260921T071637Z.json](../../backend/eval/week6/runs/judge_v2_20260921T071637Z.json) | v2 majority-of-3 run (25, 24, 24). |
| [../../backend/eval/week6/runs/v1_run.txt](../../backend/eval/week6/runs/v1_run.txt), [full_run.txt](../../backend/eval/week6/runs/full_run.txt) | Console transcripts. |
| [../../backend/scripts/evaluate_week6.py](../../backend/scripts/evaluate_week6.py) | The one-command eval: assertions, judges, tables, run files, Langfuse. |
| [../../backend/tests/test_week6_deliverables.py](../../backend/tests/test_week6_deliverables.py) | 11 tests guarding the rubric points and commit order. |
| [../week5-6-summary.md](../week5-6-summary.md) | Combined Week 5 + 6 summary, Langfuse demo path, open items. |
| [../week5/](../week5/) | Week 5 traces and taxonomy that the mode tags refer to. |

> **Important:** `docs/week6/` holds *copies*. The script reads `backend/eval/week6/`. Don't rewrite git history: the tests check commit order.

---

## 9. Common confusions

- **"The file is called `eval_set_25` but has 26 cases."** That's correct; the name comes from the "25+" requirement.
- **"agreement_after is 96.2%, so v2 is better."** No. Like-for-like, v1 is also 96.2%, and on held-out cases v2 is worse.
- **"Temperature 0 means deterministic."** Not for this model on Groq. Verdicts flipped across repeated runs.
- **"The human label is always right."** Not here. On T017 the judge caught something the human missed. The label stayed unchanged on purpose, and the disagreement is argued in writing instead.
- **"Why is T035 not a regression case?"** Its reply isn't the verbatim TR-0035 answer, so the flag was removed (it's still a mode_5 case).
- **"Overall 65% pass means the app is 65% good."** The 16 clean cases carry the average; defect modes 1, 2, 4 and 5 pass 0%.

---

## 10. Glossary

| Term | Meaning |
|---|---|
| RAG | Retrieval-augmented generation: look up documents, then have an LLM answer from them. |
| LLM-as-judge | Using an LLM to grade another model's output. |
| Ground truth | The reference labels (here, human PASS/FAIL) that other verdicts are compared with. |
| Blind labelling | Labelling without seeing the judge's verdicts. |
| Agreement rate | % of cases where judge verdict = human label. |
| agreement_before / after | Agreement for judge v1 / judge v2. |
| Deterministic assertion | A code rule that always gives the same result for the same input. |
| Zero-shot / few-shot | A prompt without / with worked examples. |
| Calibration sentence | The extra instruction in v2 about grading the core answer. |
| Held-out set | Cases not used as examples, so they test generalisation. |
| Leakage | When the answer to a test case is already in the prompt. |
| Overfitting to examples | Fixing the shown cases while getting worse on unseen ones. |
| Non-determinism | Same input, different output across runs. |
| Majority vote | Run N times (here 3) and take the most common verdict. |
| Regression case | A test copied verbatim from a real past failure. |
| Week 5 mode | One of 5 failure types found in Week 5 (e.g. mode_1 = refuses although the answer is ranked first), or `no_defect_seen`. |
| False positive (assertion) | A rule flags a problem that isn't there (T016). |
| Langfuse trace / span / generation / score | A unit of work / a step in it / an LLM-call step / a number attached to a trace. |
| Session (Langfuse) | A group of traces; here, one eval run. |
| Groq | The hosted LLM API used for all calls (`openai/gpt-oss-120b`). |

---

## 11. Key takeaways

- **Validate the judge before trusting its number.** Here it agreed with a blind human 92–96% of the time, and it agreed on 100% of defect-mode cases.
- **Order is evidence.** Labels committed before the judge ran (`d5dacc3` → `13b7728`) and a prediction committed before v2 are what make the protocol credible. Tests re-check this order.
- **Put what code can check into code.** 4 assertions vs 1 judged criterion. Rules can still be wrong, though (T016).
- **Run the judge more than once.** Temperature 0 still flips verdicts, and on 26 cases one flip moves agreement by 3.8 points.
- **Measure on held-out cases.** v2's apparent gain was leakage plus unequal measurement. Held-out agreement fell from 24/24 to 23/24.
- **Higher agreement can mean a worse judge.** On T017, v2 "agreed" by learning to accept an invented 24-hour promise.
- **Don't edit labels to win agreement.** Argue the wrong label in writing instead.
- **Averages hide failure modes.** 65% overall concealed that four defect modes pass 0%.
