# Ask My Documents

RAG app: upload documents, ask questions, get answers **only from those files**, with citations. If the answer is not in the documents, the app says it does not know.

Pipeline comes from `untitled13.py`: load `.txt` / `.md` / `.pdf`, chunk, MiniLM embeddings, FAISS search, **Groq** generation.

```text
React (TypeScript)  →  FastAPI  →  rag_service.py  →  FAISS + Groq
```

- **Frontend:** upload + chat UI, with a Week 3 / Week 4 retrieval toggle, top-k, document and product-area filters, a golden question set, and rendered citations. HTTP only in `frontend/src/services/api.ts`.
- **Backend:** FastAPI routes. No RAG code in the route files.
- **RAG service:** notebook logic (chunk, embed, retrieve, Groq) plus metadata, chunking strategies, and filtering.
- **Retrieval service:** the Week 4 stages — BM25 + dense fusion and cross-encoder reranking (`backend/app/services/retrieval.py`).

PyTorch is only the runtime for MiniLM embeddings (`sentence-transformers`). It is not the web framework. See `backend/README.md`.

## How to run

1. Backend: [backend/README.md](backend/README.md)
2. Frontend: [frontend/README.md](frontend/README.md)

You need Python 3.11+ (**arm64 build on Apple Silicon**), Node.js 18+, and a Groq API key in `backend/.env` as `GROQ_API_KEY`.

## Corpus

Seven mock help-centre articles in [sample_documents/](sample_documents/). Every article carries YAML front-matter that becomes per-chunk metadata.

| article_id | file | product_area | last_updated |
| --- | --- | --- | --- |
| KB-001 | `help_centre/airfiber_plans.md` | plans | 2026-07-15 |
| KB-002 | `help_centre/billing_faq.md` | billing | 2026-08-01 |
| KB-003 | `policies/refund_policy.txt` | billing | 2026-08-01 |
| KB-004 | `help_centre/troubleshooting_connectivity.md` | troubleshooting | 2026-08-10 |
| KB-005 | `help_centre/installation_setup.md` | installation | 2026-06-20 |
| KB-006 | `policies/account_management.md` | account | 2026-07-28 |
| KB-007 | `help_centre/airfiber_legacy_plans.md` | plans | 2026-08-22 |

KB-004 contains three troubleshooting tables (LED status, error codes, slow-speed diagnosis). Documents without front-matter still get metadata: `product_area` falls back to the top-level folder and `article_id` to the file stem, so uploaded PDFs stay filterable and citable.

## Chunking strategies

Three strategies live in [backend/app/services/chunking.py](backend/app/services/chunking.py), selected with `CHUNK_STRATEGY`:

| Strategy | Behaviour |
| --- | --- |
| `fixed` | The notebook's splitter. Collapses whitespace, slides a fixed character window. |
| `recursive` | Splits on paragraph → line → sentence → word boundaries. |
| `heading` | Markdown section-aware. Keeps tables whole and prefixes each chunk with its heading path. |

## Evaluation

```bash
cd backend && python scripts/evaluate_retrieval.py    # results.md sections 1-8  (chunking)
cd backend && python scripts/evaluate_retrieval.py --no-generate   # ...skipping the Groq transcripts
cd backend && python scripts/evaluate_week4.py        # results.md sections 9-15 (Week 4)
```

`results.md` is generated, never hand-edited, and the two scripts own separate halves of it — run them in either order. Sections 1–8 build one index per configuration and score 8 known-answer questions (3 answered only by a table), 2 ambiguous, and 3 out-of-scope. Sections 9–15 run the Week 4 experiment: 12 labelled questions, a baseline, one retrieval change, a shipping decision, and the MMR bonus. Headlines:

- `heading/1000/100` wins at Answer Hit@5 100%, citation accuracy 100%, MRR 1.000.
- Article-level hit rate saturates at 100% on a corpus this small and cannot separate strategies; the chunk-level metric can.
- Threshold tuning depends entirely on how varied the question set is. On the 8 well-formed questions the answerable and out-of-scope populations look cleanly separable at 0.37; adding 3 vaguer in-corpus questions drops the answerable floor to 0.187, below the out-of-scope ceiling of 0.310, and the separation disappears. `SCORE_THRESHOLD` is set to 0.15 — the highest value that refuses nothing answerable.
- Chunk size matters more than overlap. `chunk_size` must exceed the largest table, or the answer row gets separated from its header.
- **Week 4: the one retrieval change is shipped, and the verdict flipped once during the experiment.** On the original 6 articles BM25 + RRF measured net *negative* (Hit@1 83.3% → 75.0%) and the decision was do-not-ship. Adding an article of near-duplicate plan identifiers reversed it (Hit@1 66.7% → 75.0%). Same code, opposite verdicts — never quote a retrieval number without the corpus it was measured on.
- Section 5 pastes real transcripts: three cited answers and all three refusals, verbatim at temperature 0. Two different refusal strings appear, and the difference is the point. "How do I reset my Netflix password?" scores 0.310, clears the threshold, reaches Groq, and is refused by the system prompt alone.
- **MMR was measured and not shipped.** At the tuned lambda hit-rate@3 does not move and neither does the diversity number a person would notice; only mean pairwise cosine shifts, which is MMR reordering chunks of the same document. Push lambda far enough to change what the reader sees and it evicts the answer from the top-3 on two questions. Each golden question has exactly one correct chunk, so variety is neutral at best.
- Grading a generated answer by substring match reported 7 false generation failures out of 12 — `₹2,500` against `2500`, a Unicode hyphen in `5‑day`. Every one of those answers was correct.

## Error analysis (Week 5)

The app writes a complete trace of every `/api/chat` request when `TRACE_ENABLED=true`:
the question, the configuration the index was built under, every retrieved chunk with
each stage's score, the rendered prompt, the model and its parameters, and the raw
output. Off by default. Enough to replay an answer offline, which is the point.

```bash
cd backend
python scripts/simulate_support_traffic.py                # 148 traces -> docs/week5/traces.jsonl
python scripts/sample_traces.py --seed 20260907 --markdown  # seeded draw of 20 + 10
python scripts/replay_trace.py --from sample --pick-seed 20260907   # original vs replayed
```

Deliverables: [docs/week5/taxonomy.md](docs/week5/taxonomy.md) (5 named failure modes over
20 randomly sampled traces) and [docs/week5/notes.md](docs/week5/notes.md) (the verbatim
open coding, the replay evidence, the dated prediction and the demo-set comparison).

Headline: the largest mode, **refuses while the chunk that answers it is ranked first**,
is 3/20 (15%) in the random sample and 0/10 in the curated demo set. The prediction
targeting it is committed at `4f78158`, dated 2026-09-07, before any fix.

### The Error analysis tab

The app has two tabs. **Error analysis** (`#analysis`) renders the ranked taxonomy and
a searchable explorer over the traces, served read-only by `/api/analysis/*`:

- Click a taxonomy row to filter the list by that failure mode.
- Filter by pool, sampled, outcome or retrieval mode, or search the question and answer text.
- Open a trace for its retrieval with per-stage scores, the exact prompt that was sent, the
  raw model output, and the observation sentence written about it during open coding.
- A trace is linkable: `#analysis/TR-0055`.
- The **Trace file** selector switches between the committed 148-trace run and whatever
  `TRACE_PATH` the running server is appending to.

The taxonomy and the open coding are parsed out of `docs/week5/taxonomy.md` and `notes.md`
rather than copied into code, so the tab cannot drift from the files being graded.

**`results.md` is generated and must never be hand-edited. `docs/week5/*.md` are
hand-written analysis and must never be regenerated.** The two are opposite in exactly
the way that invites getting it backwards.

## Environment

Copy `backend/.env.example` to `backend/.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | empty | Groq API key (required for chat) |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Groq OpenAI-compatible endpoint |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Chat model |
| `EMBED_MODEL_NAME` | `all-MiniLM-L6-v2` | Embedding model |
| `CHUNK_STRATEGY` | `heading` | `fixed`, `recursive`, or `heading` |
| `CHUNK_SIZE` | `1000` | Character chunk size |
| `CHUNK_OVERLAP` | `100` | Chunk overlap |
| `TOP_K` | `5` | Retrieved chunks |
| `SCORE_THRESHOLD` | `0.15` | Below this, the app says it does not know |
| `DOCS_DIR` | `data/docs` | Uploaded files |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed UI origins |

Defaults are the values chosen in [results.md](results.md).

## RAG flow

1. Load `.txt`, `.md`, `.pdf`, splitting off YAML front-matter into metadata
2. Chunk with the configured strategy
3. Embed with MiniLM
4. Index in FAISS `IndexFlatIP`
5. Retrieve top-K, optionally filtered by `product_area` and/or a single document
6. If best score < `SCORE_THRESHOLD` → *I don't know. That isn't covered in the documents I have.* Otherwise Groq answers from context and cites `source_file`, `article_id`, and section.

## Retrieval modes

The chat toggles between two pipelines over the same index, so the difference is visible on the same question.

| | Week 3 | Week 4 |
| --- | --- | --- |
| Retrieval | Dense vectors only (FAISS cosine) | BM25 **and** dense, fused with Reciprocal Rank Fusion |
| Reranking | None | `cross-encoder/ms-marco-MiniLM-L-6-v2` over the fused pool |
| Best for | The notebook baseline; reproduces `results.md` sections 1–8 | Rare tokens (`AF-511`, `AirFiber_1199_1M`) where near-duplicate chunks compete — measurably better at rank 1, but see the caveat below |

**BM25 + RRF is the measured winner, by one question out of twelve.** Over the 12 labelled golden questions ([results.md](results.md) sections 9–14):

| | Week 3 (dense) | BM25 + RRF | Full Week 4 stack |
| --- | --- | --- | --- |
| Hit-rate@3 | 91.7% | 91.7% | 91.7% |
| Hit-rate@1 | 66.7% | **75.0%** | 66.7% |
| MRR | 0.788 | **0.819** | 0.785 |
| p50 retrieval | ~8 ms | ~8 ms | ~158 ms |

Note the third column: **stacking the cross-encoder on top of BM25 undoes the gain**, and costs 20× the latency to do it. That is why the report measures one change at a time — the shipped `week4` mode runs both stages, and the combination is worse than either the baseline or BM25 alone on this corpus.

**The corpus decides this, not the retriever.** Against the original 6 articles the same comparison came out net *negative* (Hit@1 83.3% → 75.0%) and the recorded verdict was do-not-ship, because 21 chunks give the dense retriever almost nothing to confuse the right chunk with while BM25 finds enough shared vocabulary to promote a wrong one. `help_centre/airfiber_legacy_plans.md` (KB-007) adds six plan packs that differ from the retail ones mainly in a numeric identifier — the near-duplicate condition the old verdict named as missing — and the sign reversed.

One question is 8.3 percentage points on a 12-question set, so treat this as directional rather than significant. Re-run the harness whenever the corpus changes shape; that is the variable these numbers are actually sensitive to.

Two things stay constant across modes:

- The **refusal gate** is always the best *dense cosine* against `SCORE_THRESHOLD`. A cross-encoder score is an unbounded logit and is not comparable to it.
- Both extra stages **degrade rather than fail**. Without `rank_bm25` Week 4 is dense-only; if the cross-encoder cannot load, the fused order stands. `/api/health` reports which stages are live and the UI labels the mode accordingly.

## Golden set of questions

The chat offers 14 known-answer questions from `backend/eval/golden_set.json` (served at `GET /api/golden-questions`) — two per document, plus **G13 and G14**, a pair that Week 3 retrieval misses and Week 4 recovers. Ask either with **no document selected** and flip the mode toggle: Week 3 answers *"I don't know based on the provided documents"*, Week 4 answers correctly with a citation. They are the shortest demonstration of what the mode toggle buys. Picking one fills the question box and scopes retrieval to that document; clicking the selected question again unselects it and searches the whole corpus. The **Document** control does the same thing, and always shows what is scoped.

That file is a UI fixture only. Two other files look like it and are not it:

| File | Purpose |
| --- | --- |
| `backend/eval/golden_set.json` | the chat UI's one-click prompts (this one) |
| `backend/eval/golden_set.jsonl` | the Week 4 experiment, `results.md` sections 9–14 |
| `backend/eval/gold_questions.json` | the chunking evaluation, `results.md` sections 1–8 |

Editing the UI list must not move a number in the report.

## Try it

Upload the `sample_documents/` folder, then:

- **Golden set:** open **Golden set of questions** under the message box and pick any of the 12
- **In corpus:** "What are the benefits of AirFiber_1199_1M plan"
- **Table-based:** "What does a blinking red LED on the AirFiber ONT mean?"
- **Metadata filter:** "What is the 500 rupee charge for?" with the product area set to `installation` — unfiltered this returns the relocation fee from KB-006 instead
- **Single document:** set **Document** to `billing_faq.md` and ask "What happens if my payment fails?" — every citation now comes from that one file
- **Week 3 vs Week 4:** ask "Are OTT add-on charges refundable?" in each mode and compare the top citation
- **Out of corpus:** "What is the capital of Mongolia?"
