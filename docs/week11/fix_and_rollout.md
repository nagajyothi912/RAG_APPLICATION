# Fix, prompt version bump, canary and rollback

## The failure

[F01/F02 in the suite](../../backend/eval/week11/regression_cases.jsonl): a refund question with a false premise — "does the **30 day** money back guarantee apply to me" — gets `I don't know based on the provided documents.`, although the refund policy (7 days, speed condition) is in the context. Reproduced at the production setting (no temperature sent): 9 of 9 direct probes (3 phrasings × 3 tries) refused, and in the RED suite run F01 failed on 2 of its 3 samples and F02 on all 3.

## What I ruled out first

I assumed it was retrieval. In `week4` mode the reranker puts `refund_policy.txt#0` **5th of 5** behind four unrelated `account_management` chunks, while dense cosine ranks it first (0.43). I built a fix for that (keep the best dense hit near the top of the reranked list). **It did not fix the answer:** with the refund policy moved to rank 1, the model still said "I don't know" 4 of 4 times. I reverted that code rather than ship a change that fixes nothing. The reranker ordering is a real oddity but it is not what caused this failure.

The cause is the prompt. v1 says "if the context does not contain the answer, say exactly *I don't know…*". A question that asks about a guarantee the documents never mention reads, to the model, as "the context doesn't contain the answer", even though the right reply is "no such guarantee; the policy is 7 days".

Also worth knowing: at **temperature 0** the same prompt answers correctly. The Week 5/6 evals and the Week 10 race pin temperature to 0 (per `CLAUDE.md`), so none of them could have seen this. The new suite runs at the production setting (temperature unset) with 3 samples per case, and a case passes only if all 3 pass.

## The fix (prompt layer) and the version bump

| | |
|---|---|
| `PROMPT_VERSION` | **v1 → v2** (`app/services/rag_service.py`) |
| `PROMPT_ID` | `v1-cfc04156c4e7` → `v2-e875686be844` (the SHA is derived from the templates, so the label cannot drift from the text) |
| Change | One sentence appended to `SYSTEM_PROMPT` |
| Pinned in | `tests/test_tracing.py::test_the_prompt_id_is_pinned_…` (literal updated, as that test's docstring requires) |

Added sentence:

> If the question assumes something the context does not offer (for example a guarantee, window or amount the context never mentions), do not answer "I don't know": say the documents do not mention it, then state what the context does say about that topic.

Every trace carries `generation.prompt_version` and `prompt_id`, so any answer is attributable to v1 or v2, and `find_trace.py --prompt-version v1` pulls the old cohort. Cache keys include `PROMPT_ID`, so the bump also invalidates any cached v1 answers.

## RED → GREEN

Suite: `backend/scripts/run_week11_suite.py`, 10 cases (8 guards that passed before, 2 failure cases), production temperature, 3 samples per case. Raw output: [evidence/suite_RED.txt](evidence/suite_RED.txt), [evidence/suite_GREEN.txt](evidence/suite_GREEN.txt).

| | Prompt | Suite | Failing |
|---|---|---|---|
| **RED** (before the fix) | v1 | **8/10** | F01 (2 of 3 samples), F02 (3 of 3) — the failing answer was "I don't know…" |
| **GREEN** (after the fix) | v2 | **10/10** | none; all 8 guards still pass |

Unit tests (no model calls): **243 passed** before the Week 11 work, **257 passed** after (14 new); 259 after the 2026-11-24 trace fixes (`other` span, real `finished_at`). The Week 5 "nothing behavioural was fixed after the prediction" pin still passes, because the fix is a prompt constant, not a change to `retrieve`, `_ask_inner` or `answer_with_groq`.

The case was added **before** the fix and watched failing; the RED output above is from the v1 code.

**Where the case lives:** `backend/eval/week11/regression_cases.jsonl` (F01, F02). The brief asks for it "in the Week-6 suite". I did not edit `eval_set_25.jsonl`: that file is paired with hand labels and a judge-agreement number, and `test_week6_deliverables.py` pins its history. The Week 11 suite is its own file in the same `backend/eval/` tree, run by its own script.

## Canary and rollback (two lines)

1. **Canary:** ship v2 to ~10% of chat traffic (or admin users only first) for a day; watch `find_trace.py --prompt-version v2 --text "I don't know"` against the v1 refusal rate on the same questions, and promote only if the v2 "I don't know" rate on refund questions is not higher.
2. **Rollback:** set `PROMPT_VERSION`/`SYSTEM_PROMPT` back to the v1 strings (one commit revert; the pinned test goes red until its literal is reverted too, which is the intended tripwire) and redeploy; v1 traces and the cache key space are unaffected because both are keyed on `PROMPT_ID`.

**Caveat:** this app has no traffic splitter, so the canary is a plan, not something shipped. The 10% split would need a per-request prompt switch that does not exist yet.
