# Week 4 — Debugging Retrieval: Hybrid Search, Reranking, and One Measured Change

> **In one sentence:** Week 4 adds a second way to search (BM25 keyword search, merged with the Week 3 vector search by Reciprocal Rank Fusion) and an optional cross-encoder reranker. It then tests them on 12 hand-labelled support questions, one change at a time, and decides with numbers which change to ship.
>
> **TL;DR:** The baseline (dense vector search only) found the right chunk in the top 3 for 11/12 questions (91.7%). Adding BM25 + RRF kept hit-rate@3 at 91.7% but raised hit-rate@1 from 66.7% to 75.0% and MRR from 0.788 to 0.819, for about +0.5 ms of latency. The recorded decision is **ship BM25 + RRF**, but the margin is thin: one question out of twelve. The cross-encoder alone did not help, and it cost about 20× the latency. MMR (the bonus) was measured and **not shipped**. The verdict depends on the corpus: before the near-duplicate article KB-007 was added, the same experiment said **do not ship**.

---

## 2. The problem in plain words

The app ("Ask My Documents") answers customer questions using a small help centre for a fictional internet provider called AirFiber ([`sample_documents/`](../../sample_documents/)). Week 3 built the basic RAG pipeline (*Retrieval-Augmented Generation*: find relevant text chunks first, then let an LLM answer from only those chunks). Week 3 retrieval is **dense only**. It turns the question into a vector (a list of numbers that captures meaning) and returns the chunks whose vectors are closest.

Dense search is good at meaning ("my payment didn't go through" ≈ "auto-pay fails"). It is weak at **exact rare tokens** such as an error code (`AF-511`) or a plan name (`AirFiber_1199_1M`). The embedding model blurs `AirFiber_1199_1M` into a general "some plan" area, so a chunk about a *different* plan with similar wording can rank higher than the right one.

The assignment ([`W4-Task-Set-A.md`](../assignments/W4-Task-Set-A.md)) frames it like this: the team lead wants to swap the LLM. Before anyone does that, you must **prove where failures actually happen** (retrieval or generation), make **exactly one** retrieval change, and report before/after numbers, including the latency cost.

---

## 3. Requirements

Source: [`docs/assignments/W4-Task-Set-A.md`](../assignments/W4-Task-Set-A.md), sections 2, 3, 5 and 6.

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | 12-question golden set, each tagged with the correct `chunk_id`; at least 4 with an exact token (error code, plan name, ticket id) | ⚠️ Partial | [`backend/eval/golden_set.jsonl`](../../backend/eval/golden_set.jsonl), [results.md §9](../../results.md). There are 12 questions and 5 are flagged `exact_token`: W01, W02 and W10 are plan names, W07 is an error code (`AF-511`), and W12 is a charge amount (`2500`). So 4 meet the strict "code / plan / ticket id" definition. **Partial because** results.md calls them "realistic support questions written against the … articles". They were written by the author, not taken from real support tickets as the assignment asks. No ticket-id question exists. |
| 2 | Measure baseline hit-rate@3 over all 12, before changing anything | ✅ Done | [results.md §10](../../results.md). The baseline is the untouched Week 3 `VectorStore.search` in [`rag_service.py`](../../backend/app/services/rag_service.py). Note: git history cannot show that the baseline was recorded *before* the change, because both landed in the same commit `7793536`. The harness keeps the baseline reproducible by running the unchanged Week 3 code path. |
| 3 | Label every miss R / G / Not-In-Corpus with one line of evidence; paste a tally | ✅ Done | [results.md §11](../../results.md), `classify()` in [`evaluate_week4.py`](../../backend/scripts/evaluate_week4.py). It adds a fourth class, **Gate** (explained below). The labelling is automated by the script: it reads the labelled chunk's rank and makes a live Groq call plus an LLM judge for G. It is not done by clicking through the UI. The UI does show per-stage ranks and the gate score ([`MessageBubble.tsx`](../../frontend/src/components/molecules/MessageBubble.tsx)), which works as an inspection view. |
| 4 | Make exactly ONE retrieval change, justified by the tally (BM25 + RRF with k=60, or a cross-encoder over the top 25) | ✅ Done | Chose BM25 + RRF ([results.md §12](../../results.md)). `RRF_K = 60` in [`retrieval.py`](../../backend/app/services/retrieval.py). The `use_keyword` / `rerank` flags on `search_hybrid` in [`rag_service.py`](../../backend/app/services/rag_service.py) isolate each change. The cross-encoder pool floor is `MIN_CANDIDATES = 25`. |
| 5 | Re-measure hit-rate@3 on the SAME 12, report before → after **and** p50 latency before → after | ✅ Done | [results.md §13–14](../../results.md): 91.7% → 91.7%, p50 8.4 ms → 8.9 ms. |
| 6 | Name which R-failures the change fixed and which it did not touch | ✅ Done | Per-question table in [results.md §13](../../results.md) (fixed / not fixed / regressed, at both @3 and @1). |
| Exp. output | One-paragraph justification that references the tally | ✅ Done | [results.md §12](../../results.md) |
| Exp. output | Shipping decision with the number behind it | ⚠️ Partial | [results.md §14](../../results.md) says "ship as the default retriever". **But the code does not do this.** The app's default mode is still `week3` (`ChatInput.tsx`: `useState<RetrievalMode>('week3')`, and the API's default `mode` is `week3`). The `week4` mode runs BM25 + RRF **and** the cross-encoder together (the "stacked" arm), which measured *worse* (Hit@1 66.7%). No API option runs BM25 + RRF alone. The decision is written down and measured, but it is not wired into the product. |
| Exp. output | Code diff showing exactly one retrieval change | ✅ Done | Diff block in [results.md §14](../../results.md). The real diff is in commit `7793536`. |
| Bonus | MMR over the fused list, tune lambda once, report hit-rate@3 and top-3 diversity, ship or not | ✅ Done | [results.md §15](../../results.md), `mmr_select` / `minmax` in [`retrieval.py`](../../backend/app/services/retrieval.py), `_apply_mmr` in [`rag_service.py`](../../backend/app/services/rag_service.py). Decision: not shipped. |
| Extra (not required) | UI mode toggle and a G13/G14 demo pair | ✅ Done | [`ModeToggle.tsx`](../../frontend/src/components/atoms/ModeToggle.tsx), [`RetrievalControls.tsx`](../../frontend/src/components/molecules/RetrievalControls.tsx), [`GoldenQuestions.tsx`](../../frontend/src/components/molecules/GoldenQuestions.tsx), [`golden_set.json`](../../backend/eval/golden_set.json) |

---

## 4. Concepts covered

### Dense retrieval (the Week 3 baseline)
- **What:** Each chunk and the question are turned into 384-number vectors by the MiniLM model (`all-MiniLM-L6-v2`). FAISS, a fast vector-search library, returns the chunks with the highest **cosine similarity** (a 0–1 "how similar in meaning" score).
- **Why it matters here:** It is the "before" in every comparison.
- **Where:** `VectorStore.search` in [`rag_service.py`](../../backend/app/services/rag_service.py). This code path is not modified in Week 4.

### BM25 (keyword / lexical search)
- **What:** A classic search-engine scoring formula. A chunk scores high when it contains the question's words, and **rare words count much more than common words**. This weighting is called *IDF* (inverse document frequency): a word that appears in few chunks is a strong signal.
- **Why:** A rare literal like `AirFiber_1199_1M` or `AF-511` gets a very high IDF, so BM25 can find exactly the chunk that mentions it. Dense search cannot do this reliably.
- **Where:** `BM25Index` in [`retrieval.py`](../../backend/app/services/retrieval.py), using the `rank_bm25` package. The custom `tokenize()` keeps identifiers findable both ways. `AF-511` becomes `["af", "511", "af511"]`, so a user who types it with or without the dash still matches.

### Hybrid retrieval
- **What:** Run both dense and BM25 search, then merge the two result lists.
- **Why:** Each one covers the other's blind spot. Dense handles meaning, BM25 handles exact words.

### Reciprocal Rank Fusion (RRF)
- **What:** A way to merge ranked lists using **positions, not scores**. Each list gives a chunk `1 / (k + rank)` points, and the points are added up. Here `k = 60` (`RRF_K`), the standard value from the original paper. It stops any single list's #1 from dominating.
- **Why:** BM25 scores are unbounded (e.g. 0–15+) and cosine is 0–1. Adding or averaging them is meaningless because they are on different scales. The assignment lists this as a "common mistake". Ranks are always comparable.
- **Where:** `reciprocal_rank_fusion()` in [`retrieval.py`](../../backend/app/services/retrieval.py). It is called in `search_hybrid` over the top `pool` (≥25) of each list.

### Cross-encoder reranking
- **What:** Dense search uses a *bi-encoder*: the question and the chunk are embedded **separately** and then compared. A **cross-encoder** reads the question and the chunk **together**, as one input, and outputs a relevance score called a *logit* (an unbounded number, roughly −11 to +11 here). It is more accurate per pair but much slower, so it only rescores a shortlist.
- **Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2`, about 90 MB, downloaded lazily on the first `week4` request.
- **Where:** `CrossEncoderReranker` in [`retrieval.py`](../../backend/app/services/retrieval.py). The shortlist ("candidate pool") size is `max(top_k × 4, 25)` (`CANDIDATE_MULTIPLIER`, `MIN_CANDIDATES` in `rag_service.py`). That covers the assignment's "rerank over the top 25".

### The refusal gate (unchanged, but important)
- **What:** If the best **dense cosine** in the results is below `SCORE_THRESHOLD = 0.15`, the app refuses ("I don't know…") without calling the LLM.
- **Week 4 rule:** The gate **always** uses the dense cosine, even in `week4` mode, because a rerank logit is on a different scale. See `gate_score = max(s.dense_score …)` in `RagService.ask`.

### Golden set
- **What:** A fixed list of questions, each with the **one known-correct answer chunk** (`expected_chunk_id`, e.g. `help_centre/airfiber_plans.md#1`). It is labelled before running retrieval, so the retriever's output cannot bias the labels.
- **Where:** [`backend/eval/golden_set.jsonl`](../../backend/eval/golden_set.jsonl). The ids are positional and valid **only** for chunking `heading/1000/100` (30 chunks).

### Hit@k (hit-rate@k)
- **What:** The fraction of questions where the correct chunk appears in the top *k* results. **Hit@3** is the assignment's headline metric. **Hit@1** asks whether the correct chunk was ranked first.
- **Why both:** With 12 questions, one question = 8.3 percentage points. Hit@3 is close to saturated here (11/12), so it barely moves. Hit@1 can still tell retrievers apart.

### MRR (Mean Reciprocal Rank)
- **What:** For each question take `1 / rank` of the correct chunk (rank 1 → 1.0, rank 2 → 0.5, rank 8 → 0.125), then average. It rewards ranking the answer *higher*, even inside the top 3.

### p50 latency
- **What:** The median time per query. Here it measures **retrieval only**, with no LLM call. Each query is timed 15 times (`LATENCY_REPEATS`) after a warm-up, and p50 is the median of the 12 per-question medians.

### R / G / Not-In-Corpus / Gate (failure classes)
- **R (retrieval failure):** the correct chunk exists but was not in the top 3.
- **G (generation failure):** the correct chunk was retrieved, but the LLM still answered wrongly.
- **Not-In-Corpus:** no chunk contains the answer.
- **Gate (added by this project):** retrieval found the right chunk, but the refusal threshold blocked it before the LLM ran. The project added this class because calling it G would blame the model for a decision it never made.

### Ablation / "one change at a time"
- **What:** Change exactly one variable between the "before" and "after" runs, so any difference can be attributed to that change. Stacking BM25 *and* a reranker in one run means you cannot tell which one helped. The harness therefore runs separate arms: A baseline, B +BM25/RRF, C +rerank. The stacked A+B+C is shown only as a reference.

### MMR (Maximal Marginal Relevance) — bonus
- **What:** A re-selection step that tries to make the top results **varied**. It repeatedly picks the candidate that maximises `λ × relevance − (1 − λ) × (max similarity to anything already picked)`. **λ (lambda)** sets the balance: `λ = 1.0` means pure relevance (MMR off), and a lower λ pushes harder for diversity.
- **Where:** `mmr_select` and `minmax` in [`retrieval.py`](../../backend/app/services/retrieval.py), and `_apply_mmr` in [`rag_service.py`](../../backend/app/services/rag_service.py). It is off by default (`MMR_LAMBDA_DEFAULT = None`).

### Graceful degradation
- If `rank_bm25` is missing, `week4` falls back to dense-only. If the cross-encoder cannot load, the fused order stays. `/api/health` reports `hybrid_available`, `reranker_available` and `reranker_loaded`, and the UI shows a warning ("BM25 missing — Week 4 falls back to dense").

---

## 5. What was implemented

### Retrieval flow

```text
                          question
                             │
            ┌────────────────┴────────────────┐
     mode = "week3"                     mode = "week4"
            │                                 │
  VectorStore.search                VectorStore.search_hybrid
  (FAISS cosine, top_k)                       │
            │                ┌────────────────┴───────────────┐
            │          dense ranking                    BM25 ranking
            │          (whole corpus)                 (whole corpus)
            │                └──── top pool (≥25) of each ────┘
            │                               │
            │                  Reciprocal Rank Fusion (k=60)
            │                               │
            │                 candidate pool (≥25 chunks)
            │                               │
            │           cross-encoder rerank   (if rerank=True and model loads;
            │                               │   otherwise keep the fused order)
            │                               │
            │                  MMR re-selection (only if mmr_lambda < 1.0;
            │                               │   off in the app)
            │                         top_k chunks
            └───────────────┬───────────────┘
                            │
       refusal gate: max DENSE cosine >= SCORE_THRESHOLD (0.15)?
                  │ no → "I don't know…"     │ yes
                                             ▼
                                Groq LLM answers with citations
```

### Pieces and how they connect

| Piece | What it does |
|---|---|
| `retrieval.py` (new) | `tokenize`, `BM25Index`, `reciprocal_rank_fusion`, `CrossEncoderReranker` (lazy, fails soft), `Scored` (holds every stage's score separately: dense, keyword, fused, rerank, dense rank, keyword rank), `availability()`, `mmr_select`, `minmax`. |
| `rag_service.py` | `RETRIEVAL_MODES = ("week3", "week4")`. `VectorStore.search_hybrid(..., rerank=True, use_keyword=True, mmr_lambda=None)` is the Week 4 path. `RagService.retrieve(mode=...)` picks the path per request. The gate stays on dense cosine. `golden_questions()` serves the UI list and computes `contrast_holds` live. |
| API (`/api/chat`) | Accepts `"mode": "week3" \| "week4"` (default `week3`). Each source returns per-stage scores, and the `retrieval` block reports `mode`, `hybrid`, `reranked`, `gate_score`, `refused`. |
| `evaluate_week4.py` | The experiment harness. It loads the corpus at `heading/1000/100`, verifies every gold label still contains its gold facts, and runs arms A/B/C plus the stacked arm at `TOP_K = 3`. It times latency, classifies failures (with a live Groq call and an LLM judge for G), sweeps MMR λ, and rewrites **only** the `<!-- week4:start -->…<!-- week4:end -->` block of `results.md`. |
| Frontend | `ModeToggle` (Week 3 "Dense only" / Week 4 "Hybrid + rerank"), `RetrievalControls` (mode, Top K, product area), `GoldenQuestions` (14 one-click prompts, with G13/G14 grouped as "Week 3 vs Week 4 (whole corpus)"), and `MessageBubble`, which shows "dense #7 → #1"-style movement and the gate score. |

### How "one change" is enforced in code
`search_hybrid` has two switches. The three arms are:
- **A baseline:** `VectorStore.search` (the Week 3 code itself)
- **B +BM25/RRF:** `search_hybrid(use_keyword=True, rerank=False)`
- **C +rerank:** `search_hybrid(use_keyword=False, rerank=True)`

`test_dense_only_ablation_reproduces_the_week3_ranking` and `test_use_keyword_false_actually_disables_bm25` check that the switches really isolate one variable.

### Commit history (what each commit did)
- **`7793536` "Week-4 Changes."** The bulk of the work: `retrieval.py`, `search_hybrid`, the mode toggle, `golden_set.jsonl` / `golden_set.json` (including G13/G14), `evaluate_week4.py`, the tests, results.md §9–14. It also added **all seven** sample documents, including KB-007 `airfiber_legacy_plans.md`, to git for the first time. The earlier six-article run (the "do-not-ship" verdict) was never committed. It survives only as a sentence in the README and results.md.
- **`2ccba54` "Fixed week4 issue: Added new document …"** Despite the message, this commit did **not** add KB-007, which was already there. It added the **MMR bonus** (`mmr_select`, `minmax`, `_apply_mmr`, results.md §15, `test_mmr_and_report.py`), raised `MIN_CANDIDATES` from 20 to 25 to match "rerank over the top 25", added the live `contrast_holds` check and the "week 4 only" / "both modes" badge for G13/G14, and committed the assignment docs.
- **`7609dde`** reuses the same commit message, but its content is **Week 8** (trajectory eval, `Week8Page.tsx`, a Week 8 section appended *after* the `week4:end` marker in results.md). It does not change any Week 4 code or numbers.

---

## 6. Analysis and results

All numbers come from [results.md](../../results.md) §9–15 (corpus: 7 articles, 30 chunks, `heading/1000/100`, top 3).

### Baseline (§10)
- **Hit@3 = 11/12 = 91.7%**, Hit@1 = 8/12 = 66.7%, MRR = 0.788, p50 = 8.4 ms.
- The only @3 miss is **W01** ("What OTT apps are included with AirFiber_1199_1M?"). The correct chunk sits at dense rank 8, and all of the top 3 are KB-007 legacy-plan chunks.

### Failure tally (§11)

| Class | Count |
|---|---|
| R (retrieval) | 1 (W01) |
| G (generation) | 0 |
| Gate | 1 (W09) |
| Not-In-Corpus | 0 |
| Passed | 10 |

**W09** ("engineer is coming tomorrow, what should I keep ready?") retrieved the correct chunk at rank 2, but its cosine of **0.1429** is below the threshold of 0.15. The app refused a question the documents answer. No retrieval change can fix that, because the gate reads dense cosine. The report records it and deliberately does **not** fix it, since that would be a second change.

Because @3 surfaced only one failure, the report also inspects **rank-1 failures** (W01, W02, W06, W09). In every case the right chunk was in the candidate pool, just ranked too low.

### Why BM25 + RRF was chosen (§12)
W01 and W02 share rare literals (`AirFiber_1199_1M`, `AirFiber_599_1M`, `AirFiber_1999_3M`) verbatim with their correct chunks. That is exactly the case where BM25 helps. The report honestly notes that W06 and W09 are **not** rare-literal failures, so it measured both candidates instead of only arguing for one.

### The four arms (§12)

| Arm | Hit@3 | Hit@1 | MRR | p50 |
|---|---|---|---|---|
| A. Baseline (dense) | 91.7% | 66.7% | 0.788 | 8.4 ms |
| **B. BM25 + RRF** | 91.7% | **75.0%** | **0.819** | 8.9 ms |
| C. Cross-encoder rerank | 91.7% | 66.7% | 0.785 | 165.3 ms |
| A+B+C stacked (the app's `week4` mode) | 91.7% | 66.7% | 0.785 | 158.8 ms |

How to read it: BM25 + RRF is the only arm that moves anything. The cross-encoder adds about 150 ms and does not help. Stacking it on top of BM25 **undoes** BM25's gain.

### Before → after, per question (§13)
- Hit@3: 91.7% → 91.7%. **W01 fixed** (rank 8 → 3), **W11 regressed** (rank 1 → 6). One failure was traded for another, which is not the same as no change.
- Hit@1: 66.7% → 75.0%. Fixed W02, W06, W09 and regressed W11, W12, for a net **+1 question**.
- Only W02's fix comes from the rare-literal mechanism used to justify the change. The other fixes came from ordinary word overlap. The regressions happened where common words matched a wrong chunk.
- p50: 8.4 ms → 8.9 ms (+0.5 ms). Both are dominated by encoding the query with MiniLM, so latency is not a deciding factor. Earlier runs measured 7.9 → 8.2 ms, so these medians move slightly from run to run.

### Shipping decision (§14)
**"Ship as the default retriever"**, on a narrow margin: +8.3 pp Hit@1, +0.031 MRR, 2 rank-1 regressions. The report says plainly that this is *directional evidence, not a measured effect size*, and that it would not survive a significance test on 12 questions.

### The verdict flip after KB-007
On the original **6 articles (21 chunks)**, the same comparison was **negative** (Hit@1 83.3% → 75.0%) and the verdict was **do not ship**. Dense search had little to confuse, and BM25 promoted wrong chunks. Then [`airfiber_legacy_plans.md`](../../sample_documents/help_centre/airfiber_legacy_plans.md) (KB-007) was added. It has six legacy plan packs (`AirFiber_1099_1M`, `AirFiber_1149_1M`, `AirFiber_1199_3M`, …) that differ from the retail plans mainly by a number. That created the near-duplicate condition where exact tokens matter, and the verdict flipped to ship. The report's conclusion: **"the retriever was never the variable — the corpus was."** Re-run the harness whenever `sample_documents/` changes.

### MMR bonus (§15)

| λ | Hit@3 | Hit@1 | MRR | Distinct articles in top-3 | Mean pairwise cosine |
|---|---|---|---|---|---|
| 1.00 (off) | 91.7% | 75.0% | 0.819 | 2.67 | 0.470 |
| 0.70 (tuned) | 91.7% | 75.0% | 0.833 | 2.67 | 0.438 |
| 0.50 | 75.0% | 75.0% | 0.794 | 2.83 | 0.288 |
| 0.30 | 75.0% | 75.0% | 0.783 | 2.83 | 0.221 |

(The full sweep also has λ = 0.9 and 0.8.) At the tuned λ = 0.70, the only change is a lower mean pairwise cosine, which comes from reordering chunks of the *same* article. A reader would not notice it. Lower λ values make the top 3 visibly more varied but push the answer out: at λ = 0.30, W01 drops from rank 3 to 15 and W12 from 3 to 6. **Not shipped.** Each golden question has exactly one correct chunk, so variety is neutral at best and harmful at worst.

---

## 7. What is NOT implemented, plus limitations and known gaps

1. **The shipping decision is not wired into the app.** results.md says to ship BM25 + RRF "as the default retriever". In the code, the default mode is still `week3`, and `week4` runs BM25 + RRF **plus** the cross-encoder (the stacked arm, Hit@1 66.7%, about 159 ms). No mode or API parameter exposes BM25 + RRF alone. The README admits that "the combination is worse than either the baseline or BM25 alone on this corpus."
2. **The golden set is not from real tickets.** The assignment asks for REAL support questions. These were written by the author in support-ticket style. There is no ticket-id question.
3. **The 12-question sample is tiny.** One question = 8.3 pp, and the report itself calls the result directional, not significant.
4. **W09 (Gate) is unresolved.** A correct answer is still refused because cosine 0.1429 < 0.15. Fixing this needs a refusal-design change, which was deliberately left out.
5. **The "baseline written before the change" is not visible in git.** The baseline, the change and the KB-007 article all landed in one commit (`7793536`). The pre-KB-007 negative run was never committed.
6. **Labels are tied to the chunk config.** `golden_set.jsonl` ids only work at `heading/1000/100`, and any chunking change invalidates all 12 (the tests fail loudly).
7. **G classification needs Groq.** Without a key, the harness reports G as "not measured" instead of guessing.
8. **Small doc inconsistencies.** The `evaluate_week4.py` docstring still says "the corpus is 21 chunks" (it is now 30). The README "Try it" says "pick any of the 12" golden questions while the UI shows 14. The README mentions a **Document** dropdown, but it is commented out in `RetrievalControls.tsx`. Picking a golden question still scopes by document internally.
9. **Commit messages are misleading.** `2ccba54` and `7609dde` are both titled "Added new document…". Neither adds KB-007, and `7609dde` is Week 8 work.

---

## 8. How to run and verify it

### Setup (from `backend/`, arm64 Python 3.11+ on Apple Silicon)
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install torch && pip install -r requirements.txt   # includes rank-bm25
cp .env.example .env                                   # set GROQ_API_KEY
uvicorn app.main:app --reload --port 8000
```
Frontend: `cd frontend && npm install && npm run dev` → http://localhost:5173.

### Tests (no Groq calls, safe to run)
```bash
cd backend
pytest tests/test_week4_retrieval.py tests/test_week4_eval.py tests/test_mmr_and_report.py -q
```
Expected: **47 passed** (verified while writing this guide). They cover the tokenizer, RRF ranking by position, BM25 finding `AF-511`, exact filtering, the gate using dense cosine, the 12-question golden set with ≥4 exact identifiers, every gold label containing its facts, the ablation flags, the G13/G14 split really holding, MMR at λ = 1 being the identity, and the rerank pool covering 25.

### Re-generate the numbers (calls Groq, rewrites results.md §9–15)
```bash
cd backend && python scripts/evaluate_week4.py
```
This rewrites only the block between `<!-- week4:start -->` and `<!-- week4:end -->`. Never hand-edit `results.md`.

### Check stage availability
`GET http://localhost:8000/api/health` should show `hybrid_available: true`. `reranker_loaded` becomes `true` after the first `week4` chat.

### Demo in the UI
1. Upload `sample_documents/` (all 7 articles; KB-007 is required for the demo).
2. Open **Golden set of questions** under the message box. Choose **G13** "Does the AirFiber_1199_1M pack have a fair usage cap?" or **G14** "How long is the OTT bundle valid on AirFiber_1999_3M?" from the group **"Week 3 vs Week 4 (whole corpus)"**. These deliberately do **not** scope to a document.
3. Send with the toggle on **Week 3**. Dense search ranks the answer 7th (per the `golden_set.json` notes), so it is not retrieved, and the README says the answer is "I don't know based on the provided documents".
4. Switch to **Week 4** and send again. The answer is found (e.g. "no fair-usage cap"), with a citation, and the source shows its rank movement ("dense #N → #M").
5. The badge reads **"week 4 only"** while the split holds. If KB-007 is not indexed, it reads **"both modes"**, because `contrast_holds` is computed against the live index.

Other quick checks from the README: "Are OTT add-on charges refundable?" in each mode (Week 4 puts the refund-policy clause first, as guarded by `test_week4_puts_the_answer_first_where_week3_does_not`).

---

## 9. Files for this week

| File | Purpose |
|---|---|
| [`docs/assignments/W4-Task-Set-A.md`](../assignments/W4-Task-Set-A.md) | The official assignment |
| [`backend/app/services/retrieval.py`](../../backend/app/services/retrieval.py) | BM25, RRF, cross-encoder, `Scored`, MMR helpers |
| [`backend/app/services/rag_service.py`](../../backend/app/services/rag_service.py) | `search_hybrid`, `_apply_mmr`, `retrieve(mode)`, the dense-cosine gate, `golden_questions()` / `contrast_holds` |
| [`backend/app/schemas.py`](../../backend/app/schemas.py) | `mode` field, per-stage source scores, `contrast_holds` |
| [`backend/app/api/chat.py`](../../backend/app/api/chat.py) | Passes `mode` through to the service |
| [`backend/scripts/evaluate_week4.py`](../../backend/scripts/evaluate_week4.py) | Experiment harness that writes results.md §9–15 |
| [`backend/eval/golden_set.jsonl`](../../backend/eval/golden_set.jsonl) | The 12 labelled Week 4 questions (the eval fixture) |
| [`backend/eval/golden_set.json`](../../backend/eval/golden_set.json) | The 14 UI one-click prompts, including G13/G14 (**not** an eval fixture) |
| [`sample_documents/help_centre/airfiber_legacy_plans.md`](../../sample_documents/help_centre/airfiber_legacy_plans.md) | KB-007, the near-duplicate plans that flipped the verdict |
| [`results.md`](../../results.md) §9–15 | All Week 4 numbers and decisions (generated) |
| [`backend/tests/test_week4_retrieval.py`](../../backend/tests/test_week4_retrieval.py) | Hybrid / RRF / BM25 / gate / golden-endpoint tests |
| [`backend/tests/test_week4_eval.py`](../../backend/tests/test_week4_eval.py) | Golden-set integrity, ablation flags, contrast-pair tests |
| [`backend/tests/test_mmr_and_report.py`](../../backend/tests/test_mmr_and_report.py) | MMR behaviour, pool ≥ 25, report-content checks |
| [`frontend/src/components/atoms/ModeToggle.tsx`](../../frontend/src/components/atoms/ModeToggle.tsx) | Week 3 / Week 4 switch with a degraded-mode warning |
| [`frontend/src/components/molecules/RetrievalControls.tsx`](../../frontend/src/components/molecules/RetrievalControls.tsx) | Mode, Top K, product-area controls |
| [`frontend/src/components/molecules/GoldenQuestions.tsx`](../../frontend/src/components/molecules/GoldenQuestions.tsx) | Golden question panel and the G13/G14 contrast group |
| [`frontend/src/components/molecules/MessageBubble.tsx`](../../frontend/src/components/molecules/MessageBubble.tsx) | Shows per-stage scores, rank movement, and the gate score (the "inspection view") |
| [`frontend/src/components/molecules/ChatInput.tsx`](../../frontend/src/components/molecules/ChatInput.tsx) | Holds the mode state (default `week3`); contrast questions clear the document scope |
| [`README.md`](../../README.md), [`backend/README.md`](../../backend/README.md) | "Retrieval modes", "Golden set", "What Week 4 measured" |

---

## Common confusions

- **`golden_set.json` vs `golden_set.jsonl` vs `gold_questions.json`.** The `.jsonl` file holds the 12 Week 4 labels. The `.json` file holds the 14 UI prompts and is not an eval fixture. `gold_questions.json` drives the Week 3 chunking eval (§1–8).
- **"Week 4 mode" ≠ "the shipped change".** The `week4` toggle is BM25 + RRF + rerank. The measured winner is BM25 + RRF alone.
- **`sources[].score` is always the dense cosine**, even in Week 4. Rerank logits are shown separately.
- **Gate ≠ G.** A Gate refusal never reached the LLM.
- **Flat Hit@3 ≠ "no change".** One question was fixed and a different one broke.

---

## 10. Glossary

| Term | Meaning |
|---|---|
| RAG | Retrieval-Augmented Generation: retrieve relevant text, then have an LLM answer from it |
| Chunk / `chunk_id` | A piece of a document. The id is `path#position`, e.g. `help_centre/airfiber_plans.md#1` |
| Dense retrieval | Search by meaning using embedding vectors and cosine similarity |
| Embedding / MiniLM | A vector representation of text; `all-MiniLM-L6-v2` produces 384-dimensional vectors |
| FAISS | A library for fast vector similarity search |
| Cosine similarity | How closely two vectors point the same way (higher = more similar) |
| BM25 | A keyword-ranking formula that rewards matching rare words (high IDF) |
| IDF | Inverse document frequency: rarer words get more weight |
| Hybrid retrieval | Combining dense and keyword search |
| RRF | Reciprocal Rank Fusion: merge ranked lists by summing `1/(k + rank)`, with k = 60 |
| Cross-encoder | A model that scores a (question, chunk) pair read together; accurate but slow |
| Bi-encoder | A model that embeds question and chunk separately (what dense search uses) |
| Logit | A raw, unbounded model score (not a 0–1 probability) |
| Reranking | Re-ordering a candidate shortlist with a stronger model |
| Candidate pool | The shortlist (≥25 chunks here) handed to the reranker / MMR |
| Golden set | Questions with known-correct answers, used for evaluation |
| Hit@k | Share of questions whose correct chunk is in the top k |
| MRR | Mean of 1/rank of the correct chunk |
| p50 | Median (50th percentile) latency |
| Ablation / arm | One experimental configuration that differs from the baseline by one change |
| R / G / Not-In-Corpus / Gate | Retrieval failure / generation failure / answer absent / blocked by the refusal threshold |
| `SCORE_THRESHOLD` | 0.15; below it the app refuses without calling the LLM |
| MMR / λ | Maximal Marginal Relevance; λ trades relevance (1.0) against diversity (lower) |
| Mean pairwise cosine | Average similarity among the top-3 chunks (lower = more varied) |
| LLM judge | A second LLM call that grades whether an answer states the gold facts |
| KB-007 | `airfiber_legacy_plans.md`, the near-duplicate plan article |

---

## 11. Key takeaways

- **Measure one change at a time.** The harness isolates BM25 + RRF and the cross-encoder as separate arms, and the stacked version turned out *worse* than BM25 alone.
- **Fuse ranks, not scores.** RRF (k = 60) avoids mixing BM25's unbounded scores with 0–1 cosines.
- **BM25 + RRF won by one question:** Hit@1 66.7% → 75.0%, MRR 0.788 → 0.819, Hit@3 unchanged at 91.7%, +0.5 ms. Directional, not significant.
- **The cross-encoder cost about 20× the latency (165 ms vs 8 ms) for no gain** on this corpus.
- **The corpus decided the verdict.** Without KB-007's near-duplicate plan names, the same change measured negative (83.3% → 75.0%) and was not shipped.
- **Not every failure is a retrieval failure.** W09 is a Gate failure caused by the refusal threshold, and no retriever can fix it.
- **MMR reduced similarity but not visibly, and it evicted answers at low λ**, so it was not shipped.
- **Gap to remember:** the "ship BM25 + RRF" decision is recorded but not wired in. The app defaults to Week 3, and its Week 4 mode is the stacked arm.
