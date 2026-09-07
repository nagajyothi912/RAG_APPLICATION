# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

"Ask My Documents" — a RAG app built for a Week 3 retrieval assignment. Upload `.txt` / `.md` / `.pdf`, ask questions, get answers **only** from those files with citations. If retrieval is weak, the app must say it does not know rather than fall back on model knowledge.

```
React (TS) ──HTTP──> FastAPI routes ──> RagService ──> FAISS + Groq
```

Week 4 extends it: find the retrieval failures, make **exactly one** retrieval change, and prove from the numbers whether it is worth shipping.

The assignment is as much about **measuring** retrieval as building it. `results.md` is the deliverable that records the evidence. It is generated — never hand-edit it — by two scripts that own different halves (see Evaluation harness).

## Commands

Backend (from `backend/`, venv active):

```bash
uvicorn app.main:app --reload --port 8000   # http://127.0.0.1:8000/docs
pytest                                       # all 82 tests
pytest tests/test_flow.py::test_health -v    # single test
python scripts/evaluate_retrieval.py         # regenerates results.md sections 1-8
python scripts/evaluate_retrieval.py --no-generate   # ...without the Groq transcripts in section 5
python scripts/evaluate_week4.py             # regenerates results.md sections 9-15
```

Frontend (from `frontend/`, backend must be running):

```bash
npm run dev     # http://localhost:5173, proxies /api -> 127.0.0.1:8000
npm run build   # tsc --noEmit + vite build — the only typecheck/lint gate
```

There is no linter and no frontend test runner.

### macOS environment trap

`pip install torch --index-url https://download.pytorch.org/whl/cpu` is correct on **Linux** and wrong on **macOS** — that index has no arm64 macOS wheels. Worse, if `python3` is an x86_64 build under Rosetta (check `platform.machine()`), pip resolves torch 2.2.2, the last x86_64 macOS release, which is incompatible with current `transformers`, `sentence-transformers`, and `scipy`. On this machine `/usr/local/bin/python3` is x86_64 and `/opt/homebrew/bin/python3` is arm64 — build the venv with the latter.

## Architecture

**The RAG pipeline is split in three.** [rag_service.py](backend/app/services/rag_service.py) owns loading, metadata, embedding, indexing, retrieval, and generation; [chunking.py](backend/app/services/chunking.py) owns the three chunking strategies; [retrieval.py](backend/app/services/retrieval.py) owns the Week 4 hybrid and reranking stages. `rag_service.py` is a deliberate port of the source Colab notebook (`untitled13.py`), and its module docstring records what is notebook-faithful, what was adapted for the web app, and what was added for the evaluation. **Keep that docstring in sync** — it is the contract that keeps the app traceable to the notebook.

Layering rules to preserve:

- `app/api/*.py` route files contain no RAG logic. They validate input, call `get_rag_service()`, and translate service exceptions into HTTP status codes: `NoDocumentsError` → 400, `RagGenerationError` → 502, an unresolvable `source_file` → 404, anything else → 500.
- The frontend performs **all** HTTP in [api.ts](frontend/src/services/api.ts). Components and hooks never call `fetch` directly. `ApiError` carries the FastAPI `detail` object through (including the `skipped` file list) so the UI can render per-file rejection reasons.
- UI follows Atomic Design under `frontend/src/components/`. `RagPage` is the only stateful composition point; `useDocuments`, `useChat`, and `useGoldenQuestions` own state. The chat controls (mode, top-k, document, product area) live in `ChatInput` and are snapshotted onto each `ChatMessage` as `options`, because the selects keep changing and scrollback is only readable if each turn records how it was asked.
- **The chat panel is light (`--white`); the sidebar is dark.** Several citation and filter rules were originally written for the sidebar palette and rendered near-invisible once reused in the chat panel. Anything under `.message-assistant`, `.citation-*`, `.retrieval-controls`, or `.golden-*` must be ink-on-paper, not paper-on-ink.

**In-memory index, no persistence.** `RagService` is a process-global singleton (`get_rag_service()`), the FAISS index lives only in RAM, and *any* mutation (upload or delete) calls `reindex()`, which re-reads and re-embeds every file in `DOCS_DIR`. Files on disk are the only source of truth; restarting rebuilds the index during FastAPI's `lifespan` startup. Fine at sample scale — it is O(all documents) per upload.

**Metadata comes from YAML front-matter.** `parse_front_matter` splits a leading `---` block (a flat `key: value` parser, not a YAML dependency) and `derive_metadata` produces the four required fields: `source_file`, `article_id`, `product_area`, `last_updated`. Documents *without* front-matter — user-uploaded PDFs — still get metadata: `product_area` falls back to the top-level folder and `article_id` to the file stem. Never let a chunk end up with no metadata; filtering and citations both depend on it.

**The golden set is a UI fixture, not an eval fixture.** `backend/eval/golden_set.json` holds the 14 questions the chat UI offers as one-click prompts, served by `GET /api/golden-questions`: two per document, plus **G13/G14**, a `contrast: week3-miss-week4-hit` pair kept so the mode toggle can be demonstrated on a real case rather than described. Those two are extra rather than replacements — dropping a per-document question to keep the count at 12 would leave a document unexercised. KB-007 deliberately contributes no questions; it is the distractor corpus that *causes* the G13/G14 split. `test_the_contrast_questions_really_do_split_week3_from_week4` fails if the split ever closes, because at that point the notes in the fixture and the claim in the README are both false. It is deliberately a *separate file* from `eval/gold_questions.json`, which drives `results.md` — editing the UI list must not move a number in the report. Each question's `source_file` is resolved against what is actually indexed, and `available: false` marks a question whose document has been deleted.

**G13/G14 are the one exception to golden-question scoping, and it is load-bearing.** Every other golden question scopes retrieval to its own document when picked. These two must not: they demonstrate the Week 3/Week 4 split, and that split exists *only* because KB-007's near-duplicate plan packs out-rank the answer. Scoping to `airfiber_plans.md` removes exactly those competitors, and then both modes answer — the demo silently proves nothing while still looking correct. `pickGolden` therefore clears the scope when `question.contrast` is set, they render in their own `Week 3 vs Week 4 (whole corpus)` group rather than under a document, and `test_the_api_exposes_the_contrast_flag_the_ui_depends_on` fails if the field stops being serialised.

Selecting *and unselecting* a document both go through `ChatInput.selectDocument`, the single writer of `sourceFile`, so the golden panel and the `Document` select cannot disagree about what is scoped. Clicking the already-selected golden question unselects its document — that is the only unselect affordance in the panel by request, so do not add a Clear button or a scope banner back. `activeGoldenId` means "the box holds this golden question"; anything that empties or rewrites the box drops the highlight, but never the scope — the document filter is an independent control, and silently widening the search on a keystroke is worse than leaving it pinned.

**`RagService.resolve_document` exists because upload flattens folders.** `sample_documents/` keeps `help_centre/` and `policies/`, but a browser folder upload lands files at the root of `DOCS_DIR`, so the same article is `help_centre/billing_faq.md` in one install and `billing_faq.md` in another. `resolve_document` accepts either and returns `None` when a bare name is ambiguous — the chat route turns that into a 404 rather than applying a filter that matches nothing and returns a bare refusal.

**Chunking strategies** are `fixed` (the notebook's whitespace-collapsing character window), `recursive` (paragraph → line → sentence → word), and `heading` (markdown section-aware). Size semantics differ and this matters when reading eval output: `fixed` treats `chunk_size` as a hard cap, while `recursive` and `heading` treat it as a target and may exceed it by up to `overlap`, because overlap is applied after packing.

**`chunk_size` must exceed the largest table.** This is the single most important finding in `results.md`. The LED table in KB-004 is 740 characters. At `chunk_size` 500 it splits, and the chunk holding the table *header* out-scores the chunk holding the answer *row* — so the app cites a chunk that does not contain the answer. `heading/1000/100` keeps every table whole and is the shipped default. `test_heading_strategy_keeps_a_table_intact_when_it_fits` and `test_fixed_strategy_splits_that_same_table` pin both sides of this.

**Metadata filtering is exact, not an over-fetch.** When a filter is active, `VectorStore.search` widens the FAISS search to the whole corpus and then filters the ranked list, so a matching chunk can never be dropped for falling outside a fixed candidate window. `test_filtering_is_exact_not_an_overfetch_window` guards this, and `test_hybrid_filtering_is_exact_not_an_overfetch_window` pins the same invariant for the Week 4 path — both retrievers there rank the whole corpus before the filter is applied.

**Two retrieval modes, selected per request.** `ChatRequest.mode` is `week3` (the default) or `week4`.

- **Week 3** is the notebook pipeline untouched: `VectorStore.search`, dense cosine only. Every number in `results.md`, the evaluation harness, and most of the test suite go through this path, so it must keep behaving exactly as it does.
- **Week 4** is `VectorStore.search_hybrid`: BM25 (`rank_bm25`) and dense are each ranked over the whole corpus, fused with Reciprocal Rank Fusion, and the fused pool (`max(top_k * 4, 20)`) is rescored by the `cross-encoder/ms-marco-MiniLM-L-6-v2` cross-encoder.

`search` returns `(chunk, float)` and `search_hybrid` returns `(chunk, Scored)` — deliberately different shapes, because `search`'s signature is depended on by the eval script and a dozen tests. `RagService.retrieve` normalises both to `(chunk, Scored)`.

Both extra stages **degrade rather than fail**: no `rank_bm25` means dense-only fusion, and a cross-encoder that will not load leaves the fused order standing. `retrieval.availability()` reports which stages are live and `/api/health` surfaces it, so the UI can say "Week 4 fell back to dense" instead of quietly answering in a weaker mode than the badge claims.

**The refusal gate stays on dense cosine in both modes.** A cross-encoder score is an unbounded logit (roughly -11..+11 on this corpus) and is *not* comparable to `SCORE_THRESHOLD`. After reranking, `results[0]` is also no longer necessarily the highest-cosine chunk. So `RagService.ask` passes the best dense cosine in the returned set as `answer_with_groq(..., gate_score=...)`, and the threshold keeps measuring exactly what section 5 of `results.md` measured. `test_gate_score_overrides_the_first_results_score` pins this — do not let the gate drift onto the rerank score.

**The "I don't know" guarantee has two layers**, and both matter:
1. `answer_with_groq` short-circuits before any LLM call when there are no results or `results[0][1] < SCORE_THRESHOLD`, returning `"I don't know. That isn't covered in the documents I have."`
2. The system prompt instructs the model to answer only from context and say `"I don't know based on the provided documents."` otherwise.

These are two *different* strings and tests assert on both — don't unify them.

**`SCORE_THRESHOLD` cannot be tuned to separate the two populations, and section 5 of `results.md` shows why.** Measured on the 8 well-formed gold questions alone, answerable scores bottom out at 0.424 against an out-of-scope ceiling of 0.310 — a clean split that suggests 0.37. Add the 3 deliberately vaguer filter-case questions, which are equally in-corpus, and the answerable floor drops to 0.187, *below* the out-of-scope ceiling. There is no separating value. The shipped 0.15 is the highest threshold that refuses nothing answerable.

Consequences to keep in mind before touching this:
- **The prompt-level refusal is load-bearing, not redundant.** "How do I reset my Netflix password?" scores 0.310 and reaches the LLM; only the system prompt refuses it. `test_near_miss_question_gets_past_the_threshold` exists to stop anyone deleting that layer.
- **Filtering lowers scores.** A `product_area` filter strips out higher-scoring chunks from other areas, so filtered top-1 scores run lower than unfiltered (0.095 vs 0.187 minimum). A threshold tuned on unfiltered retrieval will refuse filtered queries.
- Do not re-tune the threshold against a handful of well-formed questions. That is exactly the mistake the eval documents.

## Configuration

All settings come from `backend/.env` via pydantic-settings ([config.py](backend/app/config.py)); relative `DOCS_DIR` resolves against `backend/`. Defaults are the values chosen in `results.md`: `CHUNK_STRATEGY=heading`, `CHUNK_SIZE=1000`, `CHUNK_OVERLAP=100`, `TOP_K=5`, `SCORE_THRESHOLD=0.15`.

Two gotchas:

- `rag_service.py` snapshots `EMBED_MODEL_NAME` and `SCORE_THRESHOLD` into module-level constants at import time, so monkeypatching `settings` at runtime will not affect them — patch the module attributes instead (see `test_chat_without_api_key`).
- `.env` is gitignored and developer-local. It **overrides** the defaults in `config.py`, so a stale `.env` silently runs a configuration that differs from the documented one.

## Testing

`tests/conftest.py` does two things before `app.config` is imported: redirects `DOCS_DIR` to a temp dir, and pins the retrieval configuration via env vars so the suite does not depend on anyone's local `.env`. Anything that imports settings earlier will write into the real `backend/data/docs`.

Tests fixture off `sample_documents/` at the repo root. Groq is never called: tests stub `service.client` or exercise the sub-threshold short-circuit. `TestClient(app)` as a context manager triggers `lifespan`, so MiniLM downloads from Hugging Face on the first run.

The PDF upload path uses a PDF generated in `conftest.py` (`_pdf_bytes` writes a minimal one-page PDF with correct xref offsets). It replaced a test that read a PDF from the repo root that was never committed.

## Evaluation harness

**`results.md` has two owners and three fixtures.** Neither script writes the other's half:

| Sections | Script | Fixture | Grades |
| --- | --- | --- | --- |
| 1–8 | `evaluate_retrieval.py` | `eval/gold_questions.json` | chunk *contains the gold answer string* |
| 9–15 | `evaluate_week4.py` | `eval/golden_set.jsonl` | chunk *id* matches the human label |
| — (UI only) | none | `eval/golden_set.json` | nothing; it is the chat panel's one-click prompts |

`evaluate_week4.py` rewrites only what lies between `<!-- week4:start -->` and `<!-- week4:end -->`; `evaluate_retrieval.py` regenerates everything above and carries that block through via `_keep_week4_block`. **Section numbers are load-bearing** — tests and a dozen cross-references in the prose address sections by number, so new material goes in as a `###` subsection of an existing one. Section 15 (the MMR bonus) is the only top-level addition, and it sits at the end of the Week 4 block where nothing points past it. Run order therefore does not matter, and `test_results_md_carries_both_halves_of_the_report` fails if either half goes missing. Both scripts pin their configuration into `os.environ` *before* importing `app.config`, because `.env` is developer-local and overrides `config.py` — a stale one once published section 5 under `SCORE_THRESHOLD = 0.08` while every sentence in it argued for 0.15.

Note the near-collision: `golden_set.json` (UI) and `golden_set.jsonl` (Week 4 eval) differ by one letter and are unrelated. Editing the UI list must not move a number in the report.

### Sections 1–8

`gold_questions.json` holds 8 known-answer questions (3 answered only by a table), 2 ambiguous, 3 out-of-scope, and 3 metadata-filter cases. `evaluate_retrieval.py` builds one index per configuration in `CONFIGS` and generates its own observations from the measured numbers, so adding a question or a config updates the analysis rather than invalidating it.

Hit rates render as `6/8 (75%)` rather than a bare percentage: on a set this small one question is 12.5 points, and the assignment asks for the count.

**Section 5 is the one part of this script that calls Groq.** It pastes three cited answers and all three refusal transcripts verbatim, at `temperature=0` so re-running does not reword them. Without a `GROQ_API_KEY` the subsection records that it was skipped and the retrieval half still regenerates; `--no-generate` forces that path. O3 (`How do I reset my Netflix password?`) is the transcript worth keeping: it clears the threshold, reaches Groq, and is refused by the system prompt alone — the pasted proof that the prompt-level layer is load-bearing.

**The "retrieval that embarrassed us" subsection picks itself.** `find_embarrassment` takes the question whose rank-1 chunk is wrong in the most configurations, dumps both a failing and a passing Top-5, and writes the diagnosis from which of the two shapes it is (answer out-ranked, or answer cut away entirely). It currently lands on the LED table under `fixed/150/15`. Do not hardcode that — the point is that it re-derives if the corpus or the chunker moves.

Two hit rates are reported and the distinction is load-bearing: **Article Hit@k** (a chunk from the right article appears) saturates at 100% on a corpus this small and cannot separate strategies; **Answer Hit@k** (that chunk also contains the gold answer string) is the metric to optimise.

### Sections 9–14 (Week 4)

`golden_set.jsonl` holds 12 support questions, each labelled with the one `chunk_id` that answers it and 5 carrying an exact identifier. **The labels are positional and only valid at `heading/1000/100`** — any other chunking renumbers every chunk and silently invalidates the whole fixture. `test_every_gold_label_points_at_a_chunk_that_answers_it` is the guard.

Three things about this harness are easy to break:

- **Each arm must differ from the baseline by exactly one retrieval stage.** That is what `search_hybrid`'s `use_keyword` and `rerank` flags are for; both default to `True`, so the shipped `week4` mode is unaffected. The stacked A+B+C row is reported but explicitly *not* eligible as the single improvement. `test_use_keyword_false_actually_disables_bm25` and `test_dense_only_ablation_reproduces_the_week3_ranking` pin both ends.
- **MMR is measured, not shipped.** `search_hybrid` takes `mmr_lambda`, defaulting to `MMR_LAMBDA_DEFAULT = None`; `lam = 1.0` is the identity, so the bonus sweep's control row runs the same code path as every other row instead of branching around MMR. Relevance is min-max normalised per query inside `mmr_select` because an RRF score (~0.02) and a cross-encoder logit (-11..+11) are not on the cosine scale the similarity term uses — without that, `lam` would mean something different in every arm. Section 15 records the verdict: **do not ship**. At the tuned `lam = 0.70` hit-rate@3 and distinct-articles-in-top-3 both stand still and only mean pairwise cosine moves, which is MMR reordering chunks of the *same* document; every lambda that moves the visible number costs questions (2 lost at 0.30). `test_mmr_at_lambda_one_is_the_identity` and `test_search_hybrid_leaves_the_shipped_ranking_alone_by_default` are what keep the experiment out of the shipped ranking.
- **The candidate pool floor is 25 because the assignment says "over the top 25".** `MIN_CANDIDATES = 25`, and at the shipped `top_k = 5` the `CANDIDATE_MULTIPLIER` already exceeds it — the floor only bites at the `top_k = 3` the Week 4 harness measures at. `test_the_rerank_pool_covers_the_top_25_the_assignment_specifies` pins the number to the spec rather than to taste.
- **Hit-rate@3 is too coarse to decide anything, and was fully saturated before KB-007.** With 30 chunks the baseline scores 11/12; on the original 6 articles it scored 12/12. One question is 8.3 percentage points, so @3 cannot rank two retrievers. Hit@1 and MRR are reported alongside it and are what section 14 decides on — the same lesson as Article vs Answer Hit above. Never read a flat `91.7% → 91.7%` as "no change": here it hides one failure fixed and a different one introduced.
- **Never grade a generated answer by substring alone.** That test flagged 7 of 12 answers as generation failures when all 12 were correct — it was tripping on `₹2,500` vs `2500`, a Unicode hyphen in `5‑day`, and `isn't whitelisted` vs `not whitelisted`. A substring hit is accepted; anything else escalates to an LLM judge, and only a judge rejection is recorded as G. A false G would have argued for a prompt change that no evidence supports.

**The verdict flipped when the corpus changed, and that is the most important thing in this section.** On the original 6 articles (21 chunks) BM25 + RRF measured *negative* — Hit@1 83.3% → 75.0% — and the report said do-not-ship, naming the missing condition explicitly: too few near-duplicate candidates for a lexical signal to pay for itself. `sample_documents/help_centre/airfiber_legacy_plans.md` (KB-007) supplies that condition — six plan packs differing from the retail ones mainly in a numeric identifier — and the sign reversed: **Hit@1 66.7% → 75.0%, MRR 0.788 → 0.819, latency unchanged.** The current verdict is **ship**, on a net margin of one question out of twelve.

Two consequences for anyone touching this:

- **Never quote a Week 4 number without its corpus.** The same code produced opposite verdicts on two corpora. `results.md` numbers are only valid for the 7-article `sample_documents/` at `heading/1000/100`.
- **KB-007 is a load-bearing fixture, not filler.** Deleting it does not just shrink the corpus; it reverses the shipping decision in section 14 and makes `test_corpus_articles_all_carry_a_unique_id` fail. It also demonstrably degrades generic plan questions — reword rather than delete if it gets in the way (this is why UI golden question G02 names a plan instead of asking "which plans...").

## Week 5 error analysis

**`docs/week5/*.md` are hand-written, unlike `results.md`.** No script generates
`taxonomy.md`, `notes.md` or `prediction.md`, and nothing should. The generated
artifacts beside them are `traces.jsonl`, `sample.json` and `replay.md`, and
regenerating the traces breaks `sample.json`'s `traces_sha256` pin and orphans
every `trace_id` quoted in the taxonomy and the open coding. The two halves of
the repo are opposite in exactly the way that invites getting it backwards:
`results.md` must never be hand-edited, `docs/week5/*.md` must never be
regenerated.

**Tracing is emitted from `RagService.ask`, not the route, and not middleware.**
`ask` is the only scope where the question, every stage's score, the rendered
prompt, the raw model output and the answer all coexist; the route sees only the
returned dict, and route files here carry no RAG logic. HTTP-level rejections
(empty message, unresolvable `source_file`) never reach `ask` and are
deliberately untraced — they are input validation with no retrieval to analyse.
It is off by default (`TRACE_ENABLED`), and it must stay that way: the eval
scripts bypass `ask` entirely, and tracing `evaluate_week4.py` would dump four
near-duplicate ablation records per question into the file the error analysis
reads from.

**`answer_with_groq` grew a keyword-only `capture` out-parameter, not a wider
return type.** Six tests and both eval scripts compare its return value against a
bare refusal string. Every read off the Groq response is `getattr`-guarded
because the suite's fake clients carry no `usage` or `finish_reason`, and an
`AttributeError` there surfaces as a 502. `raw_output` is recorded *before*
`.strip()`, which is what keeps the empty-content fallback distinguishable from
the pre-LLM gate.

**`PROMPT_ID` is pinned by a test and must not drift.** `PROMPT_VERSION` is
hand-bumped so traces group into readable cohorts; `PROMPT_SHA` is derived from
both prompt templates so the version cannot drift away from the strings it names.
If `test_the_prompt_id_is_pinned_so_an_edit_cannot_change_the_prompt_silently`
fails, someone edited a prompt: bump the version, update the literal, and say so,
because every trace already on disk came from the old prompt and must stay
attributable to it.

**The app deliberately sends no temperature, and that is a recorded finding.**
Groq therefore uses its own default and the same prompt returns differently
worded text on each call, which means a live production trace is *not*
byte-replayable. `notes.md` section 2.3 records this. Do not "fix" it by
defaulting `GROQ_TEMPERATURE` to 0 — the collection run sets it, the shipped app
does not, and the gap is the point.

**The ticket bank carries no labels, and this is enforced.**
`backend/eval/week5/ticket_bank.jsonl` holds four keys per ticket and nothing
else. `test_no_ticket_carries_an_expected_answer_or_a_failure_label` exists so it
cannot acquire an `expected_chunk_id` later; adding one would make it a fourth
gold set and would retroactively invalidate the open coding, which was written
against unlabelled traces. Ticket ids are assigned after a seeded shuffle so id
order does not encode the authoring buckets. Note this is now a *fourth* eval
fixture next to `gold_questions.json`, `golden_set.json` and `golden_set.jsonl`
— it is in its own `week5/` directory rather than adding another near-identical
stem to that pile.

**The sampler's seeding contract has three parts and all three matter.** Sort ids
before sampling, because `random.sample` depends on the order of the population
and a resumed collection run reorders lines. Give each pool its own stream
(`"{seed}:random"`, `"{seed}:demo"`), because one shared stream means adding the
bonus draw perturbs the twenty already quoted. Pin the result to
`traces_sha256`. Changing any one of the three silently moves the sampled 20.

**The commit sequence is itself a deliverable — do not squash, rebase or amend
it.** Two rubric clauses are graded off `git log`: the open-coding commit
(`2b6b858`) touches exactly one markdown file, and the prediction commit
(`4f78158`, tagged `week5-prediction`) contains only `prediction.md` with no
app, script or frontend change after it. Four tests read `git log` to check
this. Rewriting that history turns them red and destroys the evidence.
