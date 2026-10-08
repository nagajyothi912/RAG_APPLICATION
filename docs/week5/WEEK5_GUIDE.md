# Week 5 — Error Analysis: Reading Real Traces to Find How the App Fails

> **TL;DR.** Week 5 is a *measuring* week, not a fixing week. The app was changed so that
> every chat request can write a full record of what happened (a **trace**). 120 support
> questions were written "blind" (without looking at the answers), run through the real
> app together with 28 demo/control questions, and that gave **148 traces**. A random,
> seeded (re-drawable) sample of **20** traces was read by hand. Each trace got one plain
> sentence (**open coding**), and those sentences were grouped into **5 failure modes**
> (the **taxonomy**). The biggest mode: *the app refuses even though the chunk that answers
> the question was ranked first*. That was **3 of 20 (15%)** in the random sample and
> **0 of 10** in the curated demo set. A dated **prediction** for fixing it was committed
> at `4f78158` on 2026-09-07, **before any code was fixed**. Later work sent the traces
> to **Langfuse** and added an **"Error analysis" tab** to the UI. The predicted fix has
> **not** been applied yet.

> **A note on where the requirements come from.** There is no official Week 5 assignment
> file in `docs/assignments/`. That folder only has Weeks 3 and 4. The requirements below
> were **reconstructed** from what already exists: the hand-written write-ups in
> `docs/week5/*.md`, [`../week5-6-summary.md`](../week5-6-summary.md), the README section
> "Error analysis (Week 5)", the tests (`test_week5_deliverables.py`, `test_tracing.py`,
> `test_analysis_api.py`), and the messages of the Week 5 commits `38ab685` … `e52c95d`.
> Wherever the write-ups say "the brief", they mean an assignment text that is not in this repo.

---

## 2. The problem in plain words

The app is "Ask My Documents". It is a question-answering assistant over a made-up
help centre for an internet provider called AirFiber. It finds relevant pieces of the
help articles and asks an LLM (on Groq) to answer from them. If nothing relevant enough
is found, it says "I don't know".

The starting complaint was vague: *"it sometimes gives wrong answers about billing"*
(see [`demo-script.md`](demo-script.md), Act 1). You can't fix that, because it has no
example, no frequency and no definition of "wrong". The app also **saved nothing**:
logs went to the terminal and disappeared, and requests had no ID. Nobody could even
point to *which* answer was wrong.

So Week 5 asks three questions, in this order:

1. **Record** what the app does, in enough detail to reproduce any answer later.
2. **Read** a fair, random selection of those records by hand and describe what went wrong.
3. **Rank** the problems by how often they happen. Then write down a falsifiable guess
   (a guess that could be proven wrong) about what fixing the top one will do, *before*
   fixing anything.

The trap to avoid is choosing the categories first and then reading the traces looking
for them. If you do that, you only find the problems you already expected.

---

## 3. Requirements

Reconstructed as explained above. ✅ = done, ⚠️ = done with a stated limit, ❌ = not done.

| # | Requirement (reconstructed) | Status | Where |
| --- | --- | --- | --- |
| 1 | Per-request trace log, complete enough to replay a request, off by default | ✅ | [`tracing.py`](../../backend/app/services/tracing.py), [`rag_service.py`](../../backend/app/services/rag_service.py) (`ask`), [`config.py`](../../backend/app/config.py) (`TRACE_ENABLED`) |
| 2 | Realistic traffic: a support-ticket bank written without seeing answers, provably before tracing existed | ✅ | [`ticket_bank.jsonl`](../../backend/eval/week5/ticket_bank.jsonl) (commit `38ab685`) |
| 3 | Collect real traces from the shipped pipeline (no dropped requests) | ✅ | [`simulate_support_traffic.py`](../../backend/scripts/simulate_support_traffic.py) → [`traces.jsonl`](traces.jsonl) (148 lines), [`run-transcript.txt`](run-transcript.txt) |
| 4 | Draw a random sample of 20 with a published seed, so anyone can draw it again | ✅ | [`sample_traces.py`](../../backend/scripts/sample_traces.py) → [`sample.json`](sample.json) |
| 5 | Replay one trace from its record and compare original vs replayed; list the fields that had to be added and what could not be rebuilt | ⚠️ | [`replay_trace.py`](../../backend/scripts/replay_trace.py), [`replay.md`](replay.md), [`notes.md`](notes.md) §2. Everything matched. But replay **from the trace's source list alone** is impossible, and byte-exact replay only works because temperature was pinned to 0 (both documented as findings) |
| 6 | Open coding: one sentence per sampled trace, describing what was seen, with no code changes during the step | ✅ | [`notes.md`](notes.md) §3; commit `2b6b858` touches only `notes.md` |
| 7 | Failure taxonomy: 4–7 named modes with counts, %, severity and an example; fits on one screen | ✅ | [`taxonomy.md`](taxonomy.md) (5 modes), [`notes.md`](notes.md) §4 |
| 8 | A dated prediction for the top mode, committed on its own before any fix | ✅ | [`prediction.md`](prediction.md), commit `4f78158`, tag `week5-prediction` |
| 9 | A three-sentence note on why a public benchmark would not find these failures | ✅ | [`notes.md`](notes.md) §6 |
| 10 | Bonus: how often the top mode appears in the curated demo set vs the random sample | ✅ | [`notes.md`](notes.md) §7, demo pool in [`sample.json`](sample.json) |
| 11 | Tests that check the deliverables (counts, seed, commit order) | ✅ | [`test_week5_deliverables.py`](../../backend/tests/test_week5_deliverables.py), [`test_tracing.py`](../../backend/tests/test_tracing.py), [`test_analysis_api.py`](../../backend/tests/test_analysis_api.py) |
| 12 | Extra: Langfuse as a second trace sink, plus a backfill of the 148 analysed traces | ✅ | [`langfuse_sink.py`](../../backend/app/services/langfuse_sink.py), [`push_traces_to_langfuse.py`](../../backend/scripts/push_traces_to_langfuse.py) |
| 13 | Extra: an "Error analysis" tab in the UI over the traces and taxonomy | ✅ | [`analysis.py`](../../backend/app/api/analysis.py), [`analysis_store.py`](../../backend/app/services/analysis_store.py), [`ErrorAnalysisPage.tsx`](../../frontend/src/components/pages/ErrorAnalysisPage.tsx) |
| 14 | Follow-up: apply the predicted fix and score the prediction (planned for 2026-09-14) | ❌ | Listed as an open item in [`../week5-6-summary.md`](../week5-6-summary.md). The gate in `rag_service.py` is unchanged |

---

## 4. Concepts covered

### Trace
**What:** One complete record of one request: the question, the settings, every chunk
the retriever found with each stage's score, the exact prompt sent to the model, the
model and its parameters, the raw model output, the final answer, and timings.
**Why:** You can't analyse answers you didn't save. A *replayable* trace also lets you
check later that what you're looking at is really what happened.
**Where:** `build_chat_record()` in [`tracing.py`](../../backend/app/services/tracing.py)
defines the whole schema. `RagService.ask()` in
[`rag_service.py`](../../backend/app/services/rag_service.py) builds a record and writes it.
Each line of [`traces.jsonl`](traces.jsonl) is one trace (JSONL = one JSON object per line).

### Observability
**What:** Being able to see what a running system did from what it records (logs,
traces, metrics), without changing the code and running it again.
**Why:** Before Week 5 the app had almost none. Tracing is the first step.
**Where:** `TRACE_ENABLED` (local file) and `LANGFUSE_ENABLED` (hosted dashboard).
Both are **off by default**.

### Langfuse
**What:** A hosted tool for viewing LLM-app traces. It lets you filter by tag, inspect
nested steps (retrieval, generation), add scores, and view latency and cost.
**Why:** Reading a 1.4 MB JSONL file by hand is painful. Langfuse is a *second sink*
(a second place the same record is sent). It does not replace the JSONL, because the
analysis is pinned to the JSONL file.
**Where:** [`langfuse_sink.py`](../../backend/app/services/langfuse_sink.py) turns the
same record dict into one Langfuse trace with a `retrieval` and a `generation` child.
A gate refusal is sent as a warning event instead of an empty generation.
[`push_traces_to_langfuse.py`](../../backend/scripts/push_traces_to_langfuse.py)
backfills (uploads after the fact) the 148 committed traces, with tags such as `week5`,
`sampled-random`, `sampled-demo`, `mode:1`…`mode:5` and `no-defect-seen`, plus a
`week5_has_defect` score.

### Refusal gate (`SCORE_THRESHOLD`)
**What:** Before calling the model, the app checks the best dense (embedding) cosine
similarity. If it is below `0.15`, the app answers "I don't know. That isn't covered in
the documents I have." and **never calls the model**. There is also a second refusal
layer: the system prompt tells the model to say "I don't know based on the provided
documents." when the context doesn't answer the question.
**Why it matters here:** The top failure mode is the gate throwing away a correct
chunk. Telling these two refusal strings apart is how you know which layer fired. The
trace records this in `answer.source` (`gate_refusal` vs `llm`).

### Blind authoring
**What:** The 120 questions were written from each article's **heading list only**, not
its body text. The pipeline was never run while writing them, and the file has no labels
(four keys per ticket: `ticket_id`, `question`, `channel`, `authored_on`).
**Why:** If you write a question after reading the sentence that answers it, it ends up
using the same words as the answer, and retrieval looks better than it really is.
**Where:** [`ticket_bank.jsonl`](../../backend/eval/week5/ticket_bank.jsonl). Its header
line lists writing-style quotas (typo, fragment, compound, follow-up, out-of-scope…)
but no per-ticket category. Commit `38ab685` came before any tracing code, and a test
checks this against `git log`.

### Seeded sample
**What:** A random selection made with a fixed **seed**, a number that makes the
"random" choice repeatable. Same seed + same file = same 20 traces, every time.
**Why:** If you hand-pick traces, the frequencies you report reflect your own choices,
not the traffic. With a seed, anyone can check the draw.
**Where:** [`sample_traces.py`](../../backend/scripts/sample_traces.py), seed `20260907`.
Three design choices: IDs are **sorted** before sampling, each pool has its **own
random stream** (`"20260907:random"`, `"20260907:demo"`), and the result is **pinned to
the trace file's sha256** in [`sample.json`](sample.json).

### Replay
**What:** Re-running a past request from its trace: rebuild the index with the recorded
settings, check that the corpus is the same, re-run retrieval, and re-send the recorded
prompt to the recorded model. Then compare old and new.
**Why:** It proves the trace really contains everything needed to reproduce the answer.
**Where:** [`replay_trace.py`](../../backend/scripts/replay_trace.py). The result is in
[`replay.md`](replay.md).

### Open coding
**What:** The first reading pass. For each trace you write **one sentence** about what
you saw, with no category, no cause and no fix. ("Coding" here means labelling
qualitative data, not programming.)
**Why:** Categories should come out of the data, not be forced onto it.
**Where:** [`notes.md`](notes.md) §3. A test checks there are exactly 20 sentences and
that they don't name a mode or suggest a fix.

### Axial coding / taxonomy
**What:** The second pass. Group the open-coding sentences into a small set of named
**failure modes**, count them, and rank them. The ranked table is the **taxonomy**.
Each trace goes into exactly one mode, or into "No defect seen".
**Why:** It turns 20 observations into a priority list.
**Where:** [`taxonomy.md`](taxonomy.md) (the table) and [`notes.md`](notes.md) §4 (which
trace went into which mode, and the hard calls).

### Failure mode
**What:** A named, recurring way the app goes wrong, described by **what a reader of the
answer would see**. For example, "Refuses while the chunk that answers it is ranked
first" instead of "retrieval issue".
**Why:** A name like "retrieval issue" is a diagnosis disguised as an observation, and
here it would be wrong, because retrieval worked. A test rejects generic retrieval words
in mode names.

### Severity
**What:** Only two levels are allowed. *embarrasses the client* means a client could
quote it back at us in a meeting. *annoys the user* means the customer gets there, but
slower or after a second message. Severity only breaks ties; count decides the ranking.

### Prediction
**What:** A written, dated statement, committed **before** the fix: which mode to target,
the one change, the expected number, and the conditions that would prove it wrong.
**Why:** Otherwise any result after the fix can be called a success. The **guardrails**
(things that must *not* get worse) stop you from "fixing" refusals by letting the app
invent answers.
**Where:** [`prediction.md`](prediction.md), commit `4f78158`, git tag `week5-prediction`.

### Corpus fingerprint and `text_sha256`
**What:** A short hash of every chunk in the index, plus a hash of each retrieved
chunk's text.
**Why:** Chunk IDs are positional, and `backend/data/docs/` is gitignored. Without the
hashes, replaying against a changed corpus would give a diff that looks plausible but
means nothing.
**Where:** `corpus_fingerprint()` in [`tracing.py`](../../backend/app/services/tracing.py).
The value at Week 5 was `6011b16fe1358dd4`.

---

## 5. What was implemented

### Pieces

| Piece | What it does |
| --- | --- |
| **Trace writer** (`tracing.py`) | Append-only JSONL writer. A lock makes concurrent requests write whole lines. It never raises, so a failed write cannot break a request, and it gives up after 3 consecutive failures. `build_chat_record()` holds the whole schema, and `answer.source` says which of the three exits fired (gate refusal, LLM answer, empty-output fallback). |
| **Hook in `RagService.ask`** | The only place where the question, every stage's score, the prompt, the raw output and the answer all exist together. It writes to the JSONL and/or sends to Langfuse. `answer_with_groq` got a keyword-only `capture` out-parameter, and prompt strings became constants with a hash-derived `PROMPT_ID` (`v1-cfc04156c4e7`). |
| **Ticket bank** | 120 blind questions, shuffled with seed `20260907` before IDs were assigned, so reading T001…T120 in order tells you nothing. |
| **Traffic simulator** | Sends 120 tickets + 14 demo questions (scoped to their document, the way the UI does it) + 14 **unscoped** controls through the real `RagService.ask`. Mode, top_k and filters come from a seeded draw that doesn't look at the question, so no question was hand-paired with a bad setting. Trace IDs: `TR-` = random pool, `TD-` = demo, `TU-` = unscoped control. |
| **Sampler** | Draws 20 from the random pool (120) and 10 from the demo pool (14). Writes `sample.json` with the seed, algorithm, Python version and trace-file sha256. |
| **Replay** | Rebuilds and re-runs one trace, and prints a side-by-side markdown report. |
| **Hand analysis** | `notes.md` (open coding, clustering, replay evidence, benchmark note, bonus), `taxonomy.md`, `prediction.md`, `demo-script.md`. |
| **Langfuse sink + backfill** | The same record dict sent to Langfuse. Trace IDs are derived with `create_trace_id(seed=trace_id)`, so re-running updates the same traces instead of duplicating them. |
| **Analysis API + UI** | `GET /api/analysis/summary`, `/api/analysis/traces` (filters: `q`, `pool`, `mode`, `status`, `sampled`, `failure_mode`, `refused`, paging), `/api/analysis/traces/{id}`. `source=analysis` (the committed 148) or `source=live` (whatever `TRACE_PATH` the server is writing to). The store **parses** the taxonomy and open coding out of `taxonomy.md` / `notes.md` instead of copying them into code, so the UI cannot drift from the graded files. |

### How they connect

```text
 ticket_bank.jsonl (120, blind, commit 38ab685)
            │
            ▼
 simulate_support_traffic.py ──(+14 demo, +14 unscoped control)──┐
            │  calls the real pipeline                            │
            ▼                                                     │
 RagService.ask ──► retrieval ──► gate (0.15) ──► Groq LLM         │
            │                                                     │
            ├──► tracing.py  ──► docs/week5/traces.jsonl (148, sha256-pinned)
            └──► langfuse_sink.py ──► Langfuse  (also: push_traces_to_langfuse.py backfill)
                                         │
       ┌─────────────────────────────────┼──────────────────────────────┐
       ▼                                 ▼                              ▼
 sample_traces.py               replay_trace.py                 /api/analysis/*
 seed 20260907                  TR-0023 → replay.md             (analysis_store.py)
 → sample.json (20 + 10)                                               │
       │                                                               ▼
       ▼                                                    Error analysis tab
 human reading: notes.md §3 open coding                     (#analysis, #analysis/TR-0055)
       → taxonomy.md (5 modes) → prediction.md (4f78158)       reads taxonomy.md + notes.md
```

### The order of commits is part of the method

| Commit | Step |
| --- | --- |
| `38ab685` | 120-ticket bank, written blind (no tracing code exists yet) |
| `7abb7d5` | Per-request trace log, off by default |
| `3d27041` | Traffic simulator, seeded sampler, single-trace replay |
| `a88ee38` | 148 traces (data only, nothing read yet) |
| `e9c2c55` | Seeded sample of 20 + 10, and the replay evidence |
| `2b6b858` | Open coding, 20 sentences. Touches only `notes.md` |
| `e99fd1d` | Failure taxonomy, 5 modes |
| `4f78158` | Prediction for mode 1, dated 2026-09-07, before any fix. Touches only `prediction.md` |
| `6a9fd7d` | Prediction hash and the benchmark note |
| `cc61dc1` | Bonus: 10 demo traces coded, demo vs random |
| `b680d3a` | Tests for the deliverables |
| `cd6a199` / `865731d` | README and CLAUDE.md, then reverted |
| `eaedae8` | Langfuse as a second sink, plus backfill |
| `e52c95d` | Week 5 UI changes |

Tests check this order by reading `git log`, so it can't be quietly rewritten.

---

## 6. Analysis & results

### The run (from [`notes.md`](notes.md) §0 and [`run-transcript.txt`](run-transcript.txt))

| | |
| --- | --- |
| Traces | 148 = 120 tickets + 14 demo + 14 unscoped control. 0 errors, 0 dropped |
| Time | 16.8 min; median latency 6.5 s per request |
| Corpus | 7 articles, 30 chunks, `heading/1000/100`, fingerprint `6011b16fe1358dd4` |
| Models | Embedder `all-MiniLM-L6-v2`, reranker `cross-encoder/ms-marco-MiniLM-L-6-v2`, LLM `openai/gpt-oss-120b` at temperature 0, max_tokens 400 |
| Traffic mix (random pool) | mode week4 94 / week3 26; top_k 5→81, 3→21, 8→13, 10→5; filters none 100, document 10, product area 10 |
| Outcomes (all 148) | answered 136, refused 12, error 0 |
| Trace file sha256 | `61f4e9637ddcf089f23a739f070c0c74bd1d15b7f4ef4ae346a10ae20a133133` |

### The 5 failure modes (20 random traces, seed 20260907)

Full table: [`taxonomy.md`](taxonomy.md). Trace-to-mode mapping: [`notes.md`](notes.md) §4.1.

| # | Failure mode | Count | % | Severity | Traces |
| --- | --- | ---: | ---: | --- | --- |
| 1 | Refuses while the chunk that answers it is ranked first | 3 | 15% | annoys the user | `TR-0055`, `TR-0072`, `TR-0084` |
| 2 | Says it does not know and still names a source file | 2 | 10% | embarrasses the client | `TR-0012`, `TR-0111` |
| 3 | Prints the citation in a bracket style no other answer uses | 2 | 10% | annoys the user | `TR-0045`, `TR-0077` |
| 4 | Tells a paying legacy subscriber it cannot say whether their plan is valid | 1 | 5% | embarrasses the client | `TR-0112` |
| 5 | Stops mid-word at the length cap and never reaches the last question | 1 | 5% | annoys the user | `TR-0035` |
| — | No defect seen | 11 | 55% | — | e.g. `TR-0098` |
| | **Total** | **20** | **100%** | | |

What each one looks like:

- **Mode 1.** `TR-0055` "how much is that?" and `TR-0084` "500": the chunk naming the
  ₹500 charge was ranked first, but the best dense score (0.1414 and 0.1289) was under
  the 0.15 gate, so **the model was never called**. `TR-0072` is a judgement call. It is a
  long complaint where the gate passed (0.5066) and the model refused, ignoring the
  migration-rules chunk ranked first.
- **Mode 2.** The document filter was set to an unrelated document. The answer is "I don't
  know…" but still has "(Source: …)" attached, so it reads as if that document was
  checked and came up empty.
- **Mode 3.** Citations printed as `【help_centre/airfiber_legacy_plans.md】` instead of
  the usual source line.
- **Mode 4.** "I have been on AirFiber_999_1M since 2024, is it still valid?" gets "I
  don't know", even though the cited article answers it in its first paragraph. That
  sentence just wasn't in the retrieved chunks.
- **Mode 5.** The answer stopped mid-word ("AirFiber") with `finish_reason: length`
  (it hit the 400-token cap) and never answered the third part of the question.

**Headline finding.** The most common failure is an *unnecessary refusal*. The retriever
found the answer and a fixed cosine threshold threw it away. One- or two-word queries
embed poorly against a ~700-character chunk, so a low score does not mean "not in the
corpus". This matches `results.md` §5, which says no single `SCORE_THRESHOLD` separates
answerable questions from out-of-scope ones on this corpus.

**Read the residual.** 11 of 20 had no defect, and **6 of those were correct refusals**
(GST, legacy pricing, Gmail password, landline bundle, a follow-up with no context, a
plan comparison under a mismatched filter). With 20 traces, one trace = 5 points, so
modes 3, 4 and 5 can't really be ranked against each other.

### The prediction ([`prediction.md`](prediction.md), commit `4f78158`, 2026-09-07)

- **Target:** mode 1. Chosen over mode 2 because mode 1 has the most traces, while mode 2
  is "a one-clause prompt edit with nothing to learn from it".
- **One change:** skip the numeric gate for queries **under four tokens** and let the
  system prompt decide. Explicitly *not* retuning `SCORE_THRESHOLD`, and *not* gating on
  the reranker score (an unbounded logit).
- **Expected** (re-run with the same bank and seeds on 2026-09-14): mode 1 goes from 3/20
  to **≤1/20** (−10 points).
- **Guardrails / falsified if** any of these happen: mode 1 still ≥2/20; a new "answers a
  question the corpus does not cover" mode at ≥1/20; "No defect seen" below 10/20;
  hit-rate@3 on the Week 4 golden set below 11/12.

### Bonus: demo set vs random sample ([`notes.md`](notes.md) §7)

| | random sample | curated demo set |
| --- | ---: | ---: |
| Mode 1 | **3/20 (15%)** | **0/10 (0%)** |
| Any mode | 9/20 (45%) | 3/10 (30%) |
| No defect seen | 11/20 (55%) | 7/10 (70%) |

The only defect in the demo set was mode 3 (bracket citations: `TD-0002`, `TD-0004`,
`TD-0011`). The **control** (the same demo questions without document scoping) was also
10/10 correct, so the UI's scoping is not what keeps the demo clean. The explanation in
the write-up: the demo questions were written by the team *with the answer in view*, so
they are paraphrases of real sentences. Mode 1 needs a query that looks nothing like its
answer ("500", "how much is that?"), and nobody puts one of those in a demo. The 15% was
invisible until someone read random traces.

### Replay result ([`replay.md`](replay.md))

`TR-0023` was picked by seeded draw (`random.Random("20260907:replay")`). Corpus
fingerprint, ranking, dense and rerank scores, gate score (0.3401), chunk sha256s and the
raw model output **all matched**, byte for byte. Both said "I don't know based on the
provided documents.", which is a correct refusal, since no chunk mentions GST.

### Why a public benchmark wouldn't catch this ([`notes.md`](notes.md) §6)

MMLU and HumanEval test knowledge the model already has. These failures are specific to
this corpus and this pipeline (the two different ₹500 charges, the legacy plans that
look like retail plans). And a benchmark that only scores the final answer string can't
tell a gate refusal apart from a genuinely unanswerable question.

---

## 7. What is NOT implemented / limitations / known gaps

- **The predicted fix was never applied, and the prediction was never scored.** The gate
  in `rag_service.py` is still `if top_score < SCORE_THRESHOLD: … return "I don't know…"`
  for every query length. `test_nothing_was_fixed_after_the_prediction_was_committed`
  and `test_the_refusal_threshold_has_not_moved_since_the_prediction` still pass. The
  re-run planned for 2026-09-14 is an unchecked open item in
  [`../week5-6-summary.md`](../week5-6-summary.md). The prediction is therefore
  **neither confirmed nor falsified**.
- **Points to check when someone does score it** (these are this guide's observations, not
  claims made in the write-ups):
  - "Under four tokens" isn't defined. "how much is that?" (`TR-0055`) is four
    whitespace-separated words, so whether it gets past the gate depends on how tokens
    are counted.
  - `TR-0072` was refused by the model, not the gate (gate score 0.5066), so the proposed
    change can't affect it. Reaching ≤1/20 therefore needs **both** `TR-0055` and
    `TR-0084` to flip.
- **Production traces are not byte-replayable.** The shipped app sends no `temperature`,
  so Groq uses its default and the wording changes on every call. Exact replay only
  worked because the collection run pinned temperature to 0.
- **Replay "from the trace alone" is impossible from the source list.** The response
  keeps only a 180-character preview per chunk. Replay works because the full prompt is
  stored separately. The fallback (re-deriving chunk text from the corpus and checking
  sha256) needs the corpus.
- **Which refusal layer fired is inferred** inside `ask`, not reported by
  `answer_with_groq` itself. A future fourth exit could be mislabelled.
- **No user or session identity, and no conversation history.** Follow-ups like
  `TR-0090` ("what if I don't?") can only be judged on what the app saw.
- **The questions are synthetic** (the traces are real). The author already knew the
  corpus had near-duplicate legacy plans. Domain familiarity can't be removed.
- **Small sample.** 20 traces, so 1 trace = 5 points. Only 30 of 148 traces have a
  human verdict; the other 118 are unlabelled. Failure modes are assigned by hand, not
  detected automatically.
- **Replay depends on the local corpus.** `backend/data/docs/` is gitignored. If your
  local corpus differs from the one at the time of the run, the fingerprint check will
  report a mismatch rather than a false match.
- **Small doc drift:** the docstring of `push_traces_to_langfuse.py` mentions a
  `week5_open_coding` score, but the code creates a score named `week5_has_defect` with
  the sentence as its comment.

---

## 8. How to run & verify

All commands are run from `backend/` with the venv active (arm64 Python 3.11+; see the
repo `CLAUDE.md`).

### Verify without calling Groq (safe, recommended)

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/test_week5_deliverables.py tests/test_tracing.py tests/test_analysis_api.py -q
```

Expected: **84 passed** (checked while writing this guide). These tests check the
120-ticket bank, the 148 traces, the seed and sha256 pin, taxonomy counts and severities,
20 open-coding sentences, the prediction commit's contents and order, the trace schema,
and the analysis API. Groq is never called, and tracing/Langfuse are forced off in
`conftest.py`.

Check the commit-order evidence yourself:

```bash
git show --stat --format= 4f78158          # only docs/week5/prediction.md
git show --stat --oneline 2b6b858          # only docs/week5/notes.md
git log --oneline 4f78158..HEAD -- backend/app/services/rag_service.py
# shows only eaedae8 (the Langfuse hook) - the gate line itself was not changed
```

Re-draw the sample (read-only on the traces; `--markdown` prints a table):

```bash
python scripts/sample_traces.py --seed 20260907 --n 20 --demo-n 10 --markdown --out /tmp/sample.json
```

You should get the same 20 `TR-` and 10 `TD-` IDs as in [`sample.json`](sample.json).
**Note:** the script always writes a file, and by default that file is
`docs/week5/sample.json`. The file also records your Python version, so a different
interpreter would change it. Always pass `--out` to a scratch path when you are only
verifying.

### See it in the UI

```bash
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev      # http://localhost:5173/#analysis
```

Open `#analysis`. You'll see the ranked taxonomy. Click a row to filter by that mode.
Open `#analysis/TR-0055`: the Retrieval tab shows the answering chunk at rank 1, and the
Prompt tab says the model was never called (gate 0.1414 vs 0.15). The **Trace file**
selector switches between the committed run and the live `TRACE_PATH`. The same data is
available directly at `GET /api/analysis/summary`, `/api/analysis/traces`, and
`/api/analysis/traces/TR-0055`.

### Commands that call Groq or write trace files (only if you mean to)

```bash
# Needs GROQ_API_KEY; ~17 min; OVERWRITES/APPENDS docs/week5/traces.jsonl and breaks the sha256 pin
python scripts/simulate_support_traffic.py --sleep 0.6
python scripts/simulate_support_traffic.py --dry-run --limit 5   # retrieval only, zero Groq calls

# Needs GROQ_API_KEY and the same local corpus (fingerprint 6011b16fe1358dd4)
python scripts/replay_trace.py --from sample --pick-seed 20260907        # picks TR-0023
# Needs LANGFUSE_ENABLED=true and Langfuse keys
python scripts/push_traces_to_langfuse.py --dry-run
```

Don't regenerate `traces.jsonl` or the `docs/week5/*.md` files. They are the graded,
hand-written record, and re-running would orphan every trace ID quoted in them.

To trace your own live requests, set `TRACE_ENABLED=true` in `backend/.env` (optionally
`TRACE_PATH`, `TRACE_INCLUDE_PROMPTS`). For Langfuse, set `LANGFUSE_ENABLED=true`,
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL`.

---

## 9. Files for this week

| File | Role |
| --- | --- |
| [`taxonomy.md`](taxonomy.md) | **Deliverable.** Ranked table of 5 failure modes over the 20 sampled traces |
| [`notes.md`](notes.md) | **Deliverable.** Run details, authoring protocol, seeded draw, replay evidence, 20 open-coding sentences, clustering, prediction proof, benchmark note, demo bonus |
| [`prediction.md`](prediction.md) | **Deliverable.** Dated prediction for mode 1 with falsification conditions (commit `4f78158`) |
| [`replay.md`](replay.md) | Side-by-side replay of `TR-0023` |
| [`demo-script.md`](demo-script.md) | 12–15 minute presentation script: five acts, likely questions, numbers to have ready |
| [`traces.jsonl`](traces.jsonl) | The 148 traces (sha256-pinned) |
| [`sample.json`](sample.json) | Seed, algorithm, sha256, the 20 + 10 sampled IDs |
| [`run-transcript.txt`](run-transcript.txt) | Tail of the collection run's console output |
| [`../week5-6-summary.md`](../week5-6-summary.md) | Summary of Weeks 5–6, Langfuse demo path, open items |
| [`../../backend/eval/week5/ticket_bank.jsonl`](../../backend/eval/week5/ticket_bank.jsonl) | 120 blind support tickets + quota header |
| [`../../backend/app/services/tracing.py`](../../backend/app/services/tracing.py) | Trace schema and JSONL writer |
| [`../../backend/app/services/langfuse_sink.py`](../../backend/app/services/langfuse_sink.py) | Second sink to Langfuse |
| [`../../backend/app/services/analysis_store.py`](../../backend/app/services/analysis_store.py) | Read-only loader; parses taxonomy/notes markdown |
| [`../../backend/app/api/analysis.py`](../../backend/app/api/analysis.py) | `/api/analysis/summary`, `/traces`, `/traces/{id}` |
| [`../../backend/app/services/rag_service.py`](../../backend/app/services/rag_service.py) | `ask()` builds and emits the trace; the gate lives here |
| [`../../backend/app/config.py`](../../backend/app/config.py) | `TRACE_*` and `LANGFUSE_*` settings (off by default) |
| [`../../backend/scripts/simulate_support_traffic.py`](../../backend/scripts/simulate_support_traffic.py) | Drives the 148 requests |
| [`../../backend/scripts/sample_traces.py`](../../backend/scripts/sample_traces.py) | Seeded sampler |
| [`../../backend/scripts/replay_trace.py`](../../backend/scripts/replay_trace.py) | Single-trace replay |
| [`../../backend/scripts/push_traces_to_langfuse.py`](../../backend/scripts/push_traces_to_langfuse.py) | Langfuse backfill with tags and scores |
| [`../../backend/tests/test_week5_deliverables.py`](../../backend/tests/test_week5_deliverables.py) | Checks deliverables, seed, counts, commit order |
| [`../../backend/tests/test_tracing.py`](../../backend/tests/test_tracing.py) | Checks trace schema, safety, Langfuse sink |
| [`../../backend/tests/test_analysis_api.py`](../../backend/tests/test_analysis_api.py) | Checks the analysis endpoints against the write-up's numbers |
| [`../../frontend/src/components/pages/ErrorAnalysisPage.tsx`](../../frontend/src/components/pages/ErrorAnalysisPage.tsx) | The Error analysis tab |
| [`../../frontend/src/components/molecules/TaxonomyTable.tsx`](../../frontend/src/components/molecules/TaxonomyTable.tsx) | Clickable taxonomy table |
| [`../../frontend/src/components/molecules/TraceList.tsx`](../../frontend/src/components/molecules/TraceList.tsx) | Trace list |
| [`../../frontend/src/components/molecules/TraceFilters.tsx`](../../frontend/src/components/molecules/TraceFilters.tsx) | Pool / sampled / outcome / mode / search filters |
| [`../../frontend/src/components/organisms/TraceDetailPanel.tsx`](../../frontend/src/components/organisms/TraceDetailPanel.tsx) | Retrieval / Prompt / Answer / Raw tabs for one trace |
| [`../../frontend/src/hooks/useErrorAnalysis.ts`](../../frontend/src/hooks/useErrorAnalysis.ts) | Data fetching and state for the tab |

---

## Common confusions

- **"Refused" has two meanings.** A *gate refusal* ("I don't know. That isn't covered in
  the documents I have.") means the model was never called. A *model refusal* ("I don't
  know based on the provided documents.") means the model was called and declined. Mode 1
  includes both kinds (`TR-0055` and `TR-0084` are gate refusals; `TR-0072` is a model
  refusal).
- **A refusal isn't automatically a defect.** 6 of the 11 clean traces are correct refusals.
- **The questions are synthetic, the traces are real.** Every trace is a real run of the
  pipeline with a real key.
- **`results.md` vs `docs/week5/*.md`.** `results.md` is *generated* by scripts and must
  never be hand-edited. `docs/week5/*.md` are *hand-written* and must never be
  regenerated. They are opposites.
- **The demo set isn't clean because the UI scopes it.** The unscoped control ruled that
  out.
- **Langfuse doesn't replace the JSONL.** The analysis is pinned to `traces.jsonl` by
  sha256. Langfuse is only a nicer place to read it.
- **Not every trace has a failure mode.** Only the 30 sampled traces (20 random + 10 demo)
  were read. The others show "not sampled", which is different from "No defect seen".

---

## 10. Glossary

| Term | Meaning |
| --- | --- |
| **RAG** | Retrieval-Augmented Generation: find relevant text chunks, then have an LLM answer using them |
| **Chunk** | A piece of a document; here split by headings, 1000 chars with 100 overlap (`heading/1000/100`) |
| **Dense score / cosine** | Similarity between the question's embedding and a chunk's embedding |
| **Reranker / rerank score** | A second model that re-orders candidates; its score is an unbounded logit, not comparable to a cosine |
| **week3 / week4 mode** | Dense-only retrieval vs BM25 + dense + RRF fusion + reranker |
| **Gate / `SCORE_THRESHOLD`** | If the best dense score < 0.15, refuse without calling the LLM |
| **Trace** | Complete record of one request, enough to replay it |
| **JSONL** | A file with one JSON object per line |
| **Sink** | A destination that trace records are written to (JSONL file, Langfuse) |
| **Observability** | Seeing what a system did from what it records |
| **Langfuse** | A hosted dashboard for LLM traces, with tags and scores |
| **Backfill** | Uploading already-collected data to a new destination after the fact |
| **Seed** | A number that makes a random draw repeatable |
| **Pool** | Group of traces: `random` (TR-, 120), `demo` (TD-, 14), `demo_unscoped` (TU-, 14) |
| **sha256 pin** | Recording a file's hash so any change to it is detected |
| **Corpus fingerprint** | A short hash of every chunk in the index |
| **Replay** | Re-running a recorded request and comparing the results |
| **Open coding** | One plain descriptive sentence per trace, with no categories |
| **Axial coding** | Grouping open codes into categories (here, failure modes) |
| **Taxonomy** | The ranked table of failure modes with counts |
| **Failure mode** | A named, recurring way the app fails, described by what a reader would see |
| **Residual** | Sampled traces with no defect ("No defect seen") |
| **Severity** | *embarrasses the client* or *annoys the user* |
| **Prediction** | A dated, committed, falsifiable claim about what a fix will do |
| **Guardrail** | A metric that must not get worse when the fix is applied |
| **Falsifiable** | Stated precisely enough that a result could prove it wrong |
| **Hit-rate@3** | Share of labelled questions whose correct chunk is in the top 3 (11/12 on the Week 4 set) |
| **`finish_reason: length`** | The model stopped because it hit `max_tokens` (400) |

---

## 11. Key takeaways

1. **Measure before fixing.** Week 5 changed no behaviour. It added recording, read
   traces, and committed a prediction, and the git history proves this order.
2. **The top failure is an unnecessary refusal.** In 3 of 20 random traces (15%) the
   answering chunk was ranked first and still not used, twice because a cosine gate of
   0.15 rejected very short queries before the model was called.
3. **Random samples tell the truth; demos don't.** Mode 1 was 15% in the random sample
   and 0% in the curated demo set, because demo questions are paraphrases of the answers.
4. **Reproducibility is designed in.** Blind authoring, a seeded content-blind traffic
   mix, sorted and seeded sampling, and sha256 pins mean anyone can re-derive the sample,
   and tests check it.
5. **Name modes by what users see,** not by guessed causes. "Retrieval issue" would have
   been wrong, because retrieval worked.
6. **Replay revealed a real finding.** Live traces aren't byte-replayable, because the app
   sends no temperature. Pinning it to 0 was what made exact replay possible.
7. **A clean residual is a result.** 11 of 20 were fine, and 6 of those were correct
   refusals. Small samples can't separate modes 3–5.
8. **Unfinished business:** the under-four-token gate change and the scoring of the
   prediction have not been done yet.
