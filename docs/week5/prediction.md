# Week 5 prediction — 2026-09-07

Committed before any fix. Written after the taxonomy and before a line of
retrieval or prompt code was touched.

## Target

**Mode 1, "refuses while the chunk that answers it is ranked first"** — 3 of 20
traces, 15%. Chosen over mode 2, which is more embarrassing per occurrence but is
a one-clause prompt edit with nothing to learn from it. Mode 1 has the most
traces and is the only mode whose fix requires a decision rather than a typo
correction.

The three traces are `TR-0055` ("how much is that?", refused at 0.1414),
`TR-0084` ("500", refused at 0.1289) and `TR-0072` (a long complaint whose
rank-1 chunk went unused). In the first two the answering chunk was ranked
first and the model was never called, at dense cosines of 0.1414 and 0.1289
against a `SCORE_THRESHOLD` of 0.15.

## The change

**One change: skip the numeric gate for queries under four tokens and let the
system prompt decide instead.** Short queries produce low cosines because a
one-token embedding aligns poorly with a 700-character chunk, not because the
corpus lacks the answer, and `results.md` section 5 already establishes that no
value of `SCORE_THRESHOLD` separates answerable from out-of-scope on this corpus
and that the prompt-level refusal is the layer doing the real work.

Not doing: retuning `SCORE_THRESHOLD`, which section 5 documents as the exact
mistake this evaluation exists to prevent. Not doing: gating on the rerank score,
which is an unbounded logit and not comparable to a cosine. One change, nothing
else.

## The prediction

Re-running the same 120-ticket bank at the same traffic seed `20260907` on
**2026-09-14**, and re-drawing 20 at the same sample seed:

- Mode 1 falls from **3/20 (15%) to 0/20 or 1/20 (≤5%)**, a delta of
  **−10 percentage points**, at least −2 traces.
- A new mode, "answers a question the corpus does not cover", stays at
  **0/20**. This is the guardrail: letting short queries past the gate must not
  start inventing answers, and if it does, the change is worse than the problem.
- "No defect seen" does not fall below **10/20 (50%)**, down at most 1 trace from
  the current 11/20.
- Hit-rate@3 on `eval/golden_set.jsonl` stays at **11/12**, unchanged, so the
  shipped retrieval decision in `results.md` section 14 still holds.

## Falsified if

Any one of these, and the change is reverted:

1. Mode 1 is still **≥ 2/20**.
2. "Answers a question the corpus does not cover" appears at **≥ 1/20**.
3. "No defect seen" drops below **10/20**.
4. Hit-rate@3 on the Week 4 golden set drops below **11/12**.

Condition 2 is the one I expect to be wrong about first, and it is deliberately
strict: a single fabricated answer costs more than the three refusals this change
is meant to recover.

## Baselines, measured 2026-09-07

| metric | value | source |
| --- | --- | --- |
| Mode 1 | 3/20 (15%) | `taxonomy.md` |
| Answers something uncovered | 0/20 (0%) | absent from `taxonomy.md` |
| No defect seen | 11/20 (55%) | `taxonomy.md` |
| Hit-rate@3, Week 4 golden set | 11/12 | `results.md` section 13 |
| Trace file | sha256 `61f4e963…a133133` | `sample.json` |
