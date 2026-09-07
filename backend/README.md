# Backend

FastAPI service for upload, indexing, and chat. RAG logic lives in `app/services/rag_service.py` and `app/services/chunking.py`. HTTP routes only call that service.

## Why PyTorch is installed

PyTorch is **not** used to serve APIs. FastAPI handles `/api/documents/upload` and `/api/chat`.

The original notebook embeds chunks with `sentence-transformers` (`all-MiniLM-L6-v2`). That library runs on PyTorch, so pip installs torch as a dependency of the embedder.

| Piece | Role |
| --- | --- |
| FastAPI | HTTP APIs |
| sentence-transformers + PyTorch | Turn text chunks into vectors |
| FAISS | Search those vectors |
| Groq | Generate the answer from retrieved chunks |

## How to run

**On macOS, use an arm64 Python.** Check first:

```bash
python3 -c "import platform; print(platform.machine())"   # must print arm64
```

If it prints `x86_64`, that interpreter runs under Rosetta and pip will resolve torch 2.2.2 — the last release with macOS x86_64 wheels — which is too old for current `transformers`, `sentence-transformers`, and `scipy`. Use `/opt/homebrew/bin/python3` instead.

```bash
cd backend
python3 -m venv .venv          # or /opt/homebrew/bin/python3 -m venv .venv on macOS
source .venv/bin/activate
pip install torch              # see the platform note below
pip install -r requirements.txt
cp .env.example .env
```

On **Linux without a GPU**, install the CPU wheel instead so pip does not pull a multi-GB CUDA stack:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Do **not** use that index on macOS — it has no arm64 macOS wheels and silently resolves to an ancient version.

Set `GROQ_API_KEY` in `.env` (required for chat). Then:

```bash
uvicorn app.main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs

The first start downloads the MiniLM model from Hugging Face.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Status, Groq configuration, chunking config, and which retrieval stages are live |
| `GET` | `/api/documents` | Indexed files with metadata, chunk counts, and known product areas |
| `GET` | `/api/golden-questions` | The 14 curated questions the chat UI offers, resolved against what is indexed |
| `POST` | `/api/documents/upload` | Multipart `files` (one file, many files, or a folder) |
| `DELETE` | `/api/documents?name=` | Remove an indexed file and rebuild the index |
| `POST` | `/api/chat` | `{ "message", "mode"?, "product_area"?, "source_file"?, "top_k"? }` → `{ "answer", "sources", "mode", "retrieval" }` |

Supported uploads: `.txt`, `.md`, `.pdf`.

`mode` is `week3` (default — dense vectors only, the notebook pipeline) or `week4` (BM25 + dense fused with RRF, then cross-encoder reranked). `source_file` accepts a relative path or a bare filename and 404s if it matches no indexed document, or if a bare name is ambiguous.

Each entry in `sources` carries `source`, `chunk_id`, `score`, `preview`, `article_id`, `product_area`, `last_updated`, and `section`, plus the per-stage scores `dense_score`, `keyword_score`, `fused_score`, `rerank_score`, `dense_rank`, `keyword_rank`, and `retriever`. `score` stays the dense cosine in both modes — it is the number `SCORE_THRESHOLD` is compared against. `rerank_score` is `null` under Week 3 and whenever the cross-encoder could not load.

The `retrieval` block reports `mode`, `top_k`, `hybrid`, `reranked`, `gate_score`, `score_threshold`, and `refused`.

### Week 4 dependencies

`rank-bm25` is in `requirements.txt`. The reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`, ~90 MB) is downloaded from Hugging Face on the **first Week 4 request**, not at startup, so a Week 3-only run never pays for it. Both stages degrade rather than fail: without `rank_bm25` Week 4 is dense-only, and a reranker that will not load leaves the fused order standing. `/api/health` reports `hybrid_available`, `reranker_available`, and `reranker_loaded`.

## Tests

```bash
pytest                                          # all
pytest tests/test_flow.py::test_health -v       # one test
pytest tests/test_metadata_and_chunking.py -q   # one file
```

`tests/conftest.py` redirects `DOCS_DIR` to a temp directory and pins the retrieval configuration from `results.md`, so the suite does not depend on your local `.env`. Groq is never called — tests stub the client or exercise the sub-threshold short-circuit.

## Evaluation

```bash
python scripts/evaluate_retrieval.py            # ../results.md sections 1-8  (chunking)
python scripts/evaluate_week4.py                # ../results.md sections 9-15 (Week 4)
python scripts/chunk_size_experiment.py         # the notebook's original 150/500/1200 sweep
```

`results.md` is generated, not hand-written, and the two scripts own different halves of it. `evaluate_week4.py` rewrites only the block between the `<!-- week4:start -->` / `<!-- week4:end -->` markers; `evaluate_retrieval.py` regenerates everything above and carries that block through untouched. Run them in either order.

Three fixtures, easily confused:

| File | Drives | Grades a chunk by |
| --- | --- | --- |
| `eval/gold_questions.json` | sections 1–8 | does it contain the gold answer string |
| `eval/golden_set.jsonl` | sections 9–14 | does its `chunk_id` match the human label |
| `eval/golden_set.json` | the chat UI's one-click prompts | nothing — it is not an eval fixture |

Note that `golden_set.json` and `golden_set.jsonl` differ by one letter and are unrelated. Editing the UI list must not move a number in the report.

`golden_set.jsonl`'s chunk ids are positional and valid **only at `heading/1000/100`**; changing chunking renumbers every chunk and invalidates all 12 labels. The suite fails loudly if that happens.

### What Week 4 measured

12 support questions, each labelled with the one chunk that answers it, 5 carrying an exact identifier.

| | Baseline (dense) | BM25 + RRF |
| --- | --- | --- |
| Hit-rate@3 | 91.7% | 91.7% |
| Hit-rate@1 | 66.7% | **75.0%** |
| MRR | 0.788 | **0.819** |
| p50 retrieval | ~8 ms | ~8 ms |

**Decision: ship** — but on a net margin of one question out of twelve, which is directional evidence rather than a measured effect size.

The result is only this way because of the corpus. Against the original 6 articles the same comparison came out **negative** (Hit@1 83.3% → 75.0%) and the verdict was do-not-ship: with 21 chunks the dense retriever had almost nothing to confuse the right chunk with, while BM25 had enough shared vocabulary to promote a wrong one. `airfiber_legacy_plans.md` (KB-007) adds six plan packs that differ from the retail ones mainly in a numeric identifier — the exact condition the old verdict named as missing — and the sign of the result flipped. **The retriever was never the variable; the corpus was.** Full analysis in [results.md](../results.md) sections 9–14.
