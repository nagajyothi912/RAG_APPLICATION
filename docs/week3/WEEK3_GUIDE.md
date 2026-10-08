# Week 3 — Ask My Documents: a RAG app that cites its sources and refuses what it cannot source

> **In one sentence / TL;DR**
> Week 3 builds "Ask My Documents": you upload `.txt`, `.md` or `.pdf` files, the backend cuts them into chunks, turns each chunk into a vector with the MiniLM embedding model, stores the vectors in a FAISS index, and answers questions with a Groq-hosted LLM that may only use the retrieved chunks. Every answer comes with citations, and if the best match scores below `SCORE_THRESHOLD` (0.15) the app says "I don't know" without calling the LLM at all. On top of that base, the Week 3 assignment (Task Set A) adds three chunking strategies, per-chunk metadata from YAML front-matter, a `product_area` filter, and a measured chunking evaluation. The winner was `heading/1000/100`, with Answer Hit@5 8/8, citation accuracy 8/8 and MRR 1.000 ([results.md](../../results.md) sections 1–8).

---

## 2. The problem in plain words

A large language model (LLM) answers from what it learned in training. It does not know your company's help-centre articles. If you ask it about a router error code it has never seen, it will often make up a fluent, plausible and wrong answer. This is called a **hallucination**.

**RAG (Retrieval-Augmented Generation)** fixes this in two steps:

1. **Retrieve:** find the few passages of your own documents that are most related to the question.
2. **Generate:** give only those passages to the LLM and tell it to answer from them alone.

This week asks three practical questions about that pipeline:

- **Does the way we cut documents into pieces ("chunking") change whether the right answer is found?** The corpus here is a mock help centre for an ISP called AirFiber. Its troubleshooting article is mostly tables (LED colour → meaning → fix, error code → cause → resolution). If a chunker cuts a table row away from its header row, the row `| Red | Blinking | Fiber cut detected ... |` loses the context that says which column is "Meaning" and which is "What to do".
- **Can we narrow the search with metadata?** Every chunk should know which article, product area and update date it came from, and the user should be able to say "only search `installation`".
- **Does the app refuse honestly?** A question the documents do not answer, such as "What is the capital of Mongolia?", must get "I don't know", not an invented answer.

The official brief is [docs/assignments/W3-Task-Set-A.md](../assignments/W3-Task-Set-A.md). Its own words: *"The measurement is the deliverable; the ingest is plumbing."*

---

## 3. Requirements — what was asked vs. what exists

Requirements come from section 2 ("Requirements"), section 3 ("Expected output"), section 5 ("Bonus") and section 6 ("Submission checklist") of [W3-Task-Set-A.md](../assignments/W3-Task-Set-A.md). The base app (upload, chat, citations, refusal) is listed first because the assignment says it extends "the app you already built in Week 3".

| # | Requirement | Status | Where |
|---|---|---|---|
| Base | Upload `.txt` / `.md` / `.pdf`; chunk; MiniLM embeddings; FAISS search; Groq answer with citations; "I don't know" below a threshold | ✅ Done | [rag_service.py](../../backend/app/services/rag_service.py) (`load_documents`, `VectorStore`, `answer_with_groq`), [api/documents.py](../../backend/app/api/documents.py), [api/chat.py](../../backend/app/api/chat.py) |
| R1 | Ingest the articles with metadata on **every** chunk: `source_file`, `article_id`, `product_area`, `last_updated` (no `source_file` = failed ingest) | ✅ Done (with a corpus caveat) | `parse_front_matter`, `derive_metadata`, `Chunk.metadata()` in [rag_service.py](../../backend/app/services/rag_service.py). Front-matter is in each file under [sample_documents/](../../sample_documents/). Tested by `test_every_corpus_chunk_carries_the_four_required_fields` in [test_metadata_and_chunking.py](../../backend/tests/test_metadata_and_chunking.py). **Caveat:** the brief describes "6 supplied articles" about a billing migration with an `ERR-4032` row. Those articles are not in the repo (`ERR-4032` appears only in the assignment files). The repo uses its own mock AirFiber help centre instead, with error codes like `AF-503`. |
| R2 | 8 known-answer questions, each pointing to article **and section**; at least 3 depend on a table row | ⚠️ Partial | [backend/eval/gold_questions.json](../../backend/eval/gold_questions.json) has 8 questions, Q2–Q4 marked `"kind": "table"`. Each has `expected_article_id`, `expected_source` and an `answer_contains` string. **There is no section field.** Neither the gold file nor results.md section 3 records the expected section. The section shows up only in the citations of the 3 generated answers. |
| R3 | Index under TWO chunking strategies (current + structure-aware that never splits a table row from its header); hit-in-top-5 as X/8 for each | ✅ Done (more than asked) | [chunking.py](../../backend/app/services/chunking.py) (`fixed` = the notebook's original, `heading` = structure-aware, plus `recursive`). Nine configurations measured in [results.md](../../results.md) sections 1–2. Script: [evaluate_retrieval.py](../../backend/scripts/evaluate_retrieval.py). |
| R3b | "Per-question record shown" and "the search-only dump for all 8 questions under both strategies" | ⚠️ Partial | results.md section 3 gives the per-question table **only for the best configuration** (`heading/1000/100`). For the other configurations, section 6 lists only which questions failed. No full top-5 dump of all 8 questions exists for the `fixed` strategy. |
| R4 | `product_area` metadata filter + one query where filtering changes top-1, with both result lists and scores | ✅ Done | `VectorStore.search(filters=...)` and `_matches` in [rag_service.py](../../backend/app/services/rag_service.py). `product_area` / `source_file` handling in [api/chat.py](../../backend/app/api/chat.py). Three cases (F1–F3) with full lists in results.md section 4. UI dropdown in [ChatInput.tsx](../../frontend/src/components/molecules/ChatInput.tsx). |
| R5a | 3 answerable questions through generation, a citation per claim resolving to a real `chunk_id` and article | ⚠️ Partial | results.md section 5 has 3 verbatim answers (Q1–Q3). Under each is a table of every context chunk with its `chunk_id` and whether it contains the gold answer. **But** the model's own text cites the file (and sometimes the article and section) once per answer. It does not cite a `chunk_id` for each claim, and nothing in the code enforces per-claim citations. The `chunk_id` link comes from the API's `sources` list, not from the answer text. |
| R5b | 3 out-of-corpus questions refused, transcripts pasted | ✅ Done | results.md section 5: O1 and O2 are refused by the pre-LLM gate, O3 by the system prompt. Gate code is in `answer_with_groq`. Tests are in [test_filtering_and_refusal.py](../../backend/tests/test_filtering_and_refusal.py). |
| R6 | Index the new articles only; do not re-index the historical corpus; say so | ⚠️ Partial / not applicable | results.md section 8, "Ingest scope", says no historical corpus exists, and the 7 articles under `sample_documents/` are the whole corpus. In the code, `RagService.ingest_uploads` calls `reindex()`, which **rebuilds the whole index from every file in `DOCS_DIR`**. Upload is not incremental. |
| Out | One paragraph naming the chunker you keep and why | ✅ Done | results.md section 8 ("Final chunking decision") and section 7 (observations) |
| Out | Code diff showing the second chunker and the metadata fields | ⚠️ Partial | results.md section 8 "Code diff" is a **simplified sketch**. It names helpers (`split_on_headings`, `pack_sections`, `top_level_folder`) that do not exist in the code. The real code is `chunk_by_heading` / `_blocks` in [chunking.py](../../backend/app/services/chunking.py) and `derive_metadata` in [rag_service.py](../../backend/app/services/rag_service.py). The real change is in git commit `7793536`. |
| Rubric | "One documented retrieval that embarrassed you, with its diagnosis" | ✅ Done | results.md section 6, "The retrieval that embarrassed us" (Q2 under `fixed/150/15`) |
| Bonus | A question where the structure-aware chunker wins retrieval but loses on the final answer; both answers side by side | ❌ Not done | Nothing in results.md sections 1–8 or in `evaluate_retrieval.py`. (The "Bonus" sections later in results.md belong to Week 4 MMR and Week 7/8.) |

---

## 4. Concepts covered

**Chunk / chunking.** A *chunk* is a small piece of a document, here a few hundred characters. *Chunking* is the rule that cuts documents into chunks. The whole chunk is turned into one vector, so its boundaries decide what can be found. If a chunk is too small, the answer gets separated from the words that make it findable. If it is too big, the answer gets diluted by unrelated text. Code: [chunking.py](../../backend/app/services/chunking.py).

**The three chunking strategies** (all in `chunking.py`, chosen by `CHUNK_STRATEGY`):
- `fixed` (`chunk_fixed_text`): the original notebook splitter, kept byte-for-byte. It collapses all whitespace (so table line breaks disappear) and slides a window of `chunk_size` characters, stepping back `overlap` characters each time. `chunk_size` is a hard cap.
- `recursive` (`chunk_recursive`): tries to split on paragraph breaks first, then lines, then sentences (`". "`), then words, then characters. It greedily packs pieces up to `chunk_size`. Here `chunk_size` is a target and can be exceeded by up to `overlap`.
- `heading` (`chunk_by_heading`): the **structure-aware** strategy. It cuts at markdown `#` headings. A section that fits becomes one chunk. A section that is too big is packed from paragraph "blocks", where `_blocks` treats each contiguous run of `|` table lines as **one indivisible block**. Every chunk is prefixed with its heading path, such as `Troubleshooting AirFiber connectivity > Error codes`, so even a bare table "knows" what it is about. One limit: a table bigger than the budget is still split recursively. That is why `chunk_size` must exceed the largest table. The tables in KB-004 measure 740, 616 and 628 characters.

**Overlap.** The number of characters repeated from the end of one chunk at the start of the next. It helps when an answer straddles a boundary, and it costs extra chunks.

**Embedding.** A list of numbers (a vector) that represents the meaning of a text. Similar meanings give vectors that point in similar directions. This app uses `all-MiniLM-L6-v2` from `sentence-transformers`, with `normalize_embeddings=True`. See `VectorStore._embed` in [rag_service.py](../../backend/app/services/rag_service.py). PyTorch is installed only because sentence-transformers runs on it ([backend/README.md](../../backend/README.md)).

**Cosine similarity.** A score from −1 to 1 for how closely two vectors point the same way. Because the vectors are normalized, a plain dot product ("inner product") equals the cosine.

**FAISS / `IndexFlatIP`.** FAISS is a library for fast vector search. `IndexFlatIP` is the simplest index type: it compares the query against every stored vector by inner product, which is exact rather than approximate. It is built in `VectorStore.index` and lives in memory, so it is rebuilt from the files on disk at every start.

**Top-k.** How many best-scoring chunks retrieval returns. The default is `TOP_K=5` (it was 3 in the first commit).

**Metadata and YAML front-matter.** Each sample article starts with a block like:
```yaml
---
article_id: KB-004
title: Troubleshooting AirFiber connectivity
product_area: troubleshooting
last_updated: 2026-08-10
---
```
`parse_front_matter` (a deliberately tiny `key: value` parser, not a YAML library) splits this block off. `derive_metadata` turns it into the four required fields. When there is no front-matter, `article_id` falls back to the file stem, `product_area` to the top-level upload folder (or `uncategorized`), and `last_updated` to `unknown`. Every `Chunk` carries these fields.

**Metadata filtering.** Restricting retrieval to chunks whose metadata matches, such as `product_area = installation` or one `source` file. When a filter is active, `VectorStore.search` searches the **whole** corpus and then drops non-matching chunks. A matching chunk can therefore never be lost because it fell outside a fixed candidate window ("exact, not over-fetch"). This is tested by `test_filtering_is_exact_not_an_overfetch_window`.

**Refusal gate / `SCORE_THRESHOLD`.** If the best retrieved cosine is below `SCORE_THRESHOLD` (0.15), `answer_with_groq` returns `I don't know. That isn't covered in the documents I have.` and **makes no API call**.

**Grounding prompt (second refusal layer).** The system prompt is: *"Answer ONLY using the provided context. Every answer must name the source file it came from. If the context does not contain the answer, say exactly: "I don't know based on the provided documents." Never use outside knowledge."* This is the "forced, not suggested" refusal that the brief's "Common mistakes" asks for. If Groq returns empty content, the code also falls back to that refusal string.

**Citation.** `format_citation` puts a header such as `[Source: help_centre/troubleshooting_connectivity.md, article_id: KB-004, section: Troubleshooting AirFiber connectivity > Error codes, chunk #2]` above each chunk in the LLM's context. The API returns a `sources` list with `source`, `chunk_id`, `score`, `article_id`, `product_area`, `last_updated`, `section` and `preview`, and the UI renders it.

**Evaluation metrics** (defined at the top of results.md and in `evaluate_retrieval.py`):
- **Article Hit@k:** a chunk from the expected article is somewhere in the top-k.
- **Answer Hit@k:** a top-k chunk is from the expected article **and** contains the gold answer string (for example `"oversubscribed"` for AF-503). This is the stricter metric that matters.
- **MRR (Mean Reciprocal Rank):** the average of 1/(rank of the first answer-bearing chunk). 1.000 means it was always rank 1.
- **Citation accuracy:** Answer Hit@1, meaning the top source shown really contains the answer.

---

## 5. What was implemented

### How the pieces connect

```text
 UPLOAD                                              ASK
 ------                                              ---
 Browser (React, frontend/)                          Browser: question + optional
   | POST /api/documents/upload                        product_area / document filter
   v                                                    | POST /api/chat
 api/documents.py  (no RAG logic)                       v
   v                                                  api/chat.py  (builds filters; 404 if
 RagService.ingest_uploads                              |          the document name is unknown)
   - sanitize path, reject non .txt/.md/.pdf, empty     v
   - save into DOCS_DIR (data/docs)                   RagService.ask -> _ask_inner
   v                                                    v
 RagService.reindex()  (rebuilds the WHOLE index)     retrieve(mode="week3")
   v                                                    = VectorStore.search(question, top_k, filters)
 load_documents: walk DOCS_DIR                          - embed question with MiniLM
   - read .txt/.md, or .pdf via pypdf                   - FAISS inner product (= cosine)
   - parse_front_matter + derive_metadata               - apply metadata filter on the ranked list
   v                                                    v
 chunk_document(strategy = fixed|recursive|heading)   gate_score = best cosine
   v                                                    |
 Chunk(text, source, chunk_id, article_id,              +-- < 0.15 --> "I don't know. That isn't covered
       product_area, last_updated, section)             |              in the documents I have."  (no LLM call)
   v                                                    |
 VectorStore.index: MiniLM embeddings                   +-- >= 0.15 -> answer_with_groq
   -> FAISS IndexFlatIP (in memory)                                    context = citation header + chunk text
                                                                       Groq (openai/gpt-oss-120b, max 400 tokens)
                                                                       -> answer (or "I don't know based on the
                                                                          provided documents.")
                                                                       + sources[] with chunk_id, scores, metadata
```

### The pieces, one by one

1. **Base app (commit `a1eea12`, "RAG APPLICATION").** This commit ports the Colab notebook (`untitled13.py`, deleted in `188f4c5`) to FastAPI + React. It has the fixed character chunker, MiniLM + FAISS, Groq generation, the "I don't know" fallback, upload/list/delete endpoints, and the first tests ([test_chunking.py](../../backend/tests/test_chunking.py), [test_flow.py](../../backend/tests/test_flow.py)). Its defaults were `CHUNK_SIZE=500`, `CHUNK_OVERLAP=50`, `TOP_K=3`, `SCORE_THRESHOLD=0.08`. Only 3 sample documents existed then.
2. **Task Set A extension.** This added the three strategies, the metadata, the filter, the gold questions, the evaluation script, the generated `results.md` and the full 6-article corpus. All of it landed in commit `7793536` ("Week-4 Changes"), **together with** the Week 4 hybrid retrieval. Git therefore has no separate "Week 3 extension" commit. The defaults moved to `heading / 1000 / 100`, `TOP_K=5` and `SCORE_THRESHOLD=0.15` ([config.py](../../backend/app/config.py), [.env.example](../../backend/.env.example)).
3. **Chunking** ([chunking.py](../../backend/app/services/chunking.py)). The `STRATEGIES` dict maps names to functions. `chunk_document` raises `ValueError` for an unknown name.
4. **Metadata** ([rag_service.py](../../backend/app/services/rag_service.py)). `METADATA_FIELDS`, `parse_front_matter`, `derive_metadata` and the extended `Chunk` dataclass. `source_file` is a property alias for the notebook's `source` field.
5. **Retrieval + filter.** This is `VectorStore.search`, the "week3" mode. The API also accepts `source_file` and maps it to the internal `source` filter through `resolve_document`. An unknown name is a 404, never a silent empty filter.
6. **Generation + refusal.** `answer_with_groq`, the two refusal strings, and `format_citation`.
7. **API.** `/api/health` (reports the chunk strategy, size, overlap, top_k and threshold), `/api/documents` (metadata, chunk counts, product areas), `/api/documents/upload`, `DELETE /api/documents?name=`, and `/api/chat`.
8. **UI** ([frontend/](../../frontend/)). Upload panel, document list with article ID / product area / chunk count / last updated, a product-area dropdown, and citations under each answer ([MessageBubble.tsx](../../frontend/src/components/molecules/MessageBubble.tsx) shows `article_id`, section, score and `chunk #`).
9. **Evaluation** ([evaluate_retrieval.py](../../backend/scripts/evaluate_retrieval.py)). It builds 9 separate indexes (`CONFIGS`) over the same corpus and scores the gold set at top-3 and top-5. It then picks the best configuration by Answer Hit@5 → citation accuracy → MRR, and runs the filter cases, the threshold sweep and the "embarrassment" search on it. It also runs generation through Groq at temperature 0, unless `--no-generate` is passed or no key is set. Finally it writes results.md sections 1–8. [chunk_size_experiment.py](../../backend/scripts/chunk_size_experiment.py) is the notebook's original 150/500/1200 sweep, which uses the `fixed` strategy.

> **Later, not Week 3:** the `week4` retrieval mode (BM25 + RRF + cross-encoder rerank, [retrieval.py](../../backend/app/services/retrieval.py)), the Week 3 / Week 4 mode toggle, the 14 one-click golden questions, and KB-007 (`airfiber_legacy_plans.md`) all came in Week 4. They are mentioned here only so they do not confuse you when you open the code. The `week3` mode is the default and is exactly the pipeline described above.

---

## 6. Analysis & results

All numbers are from [results.md](../../results.md) sections 1–8. Note: results.md was regenerated after KB-007 was added in Week 4, so it reports **7 articles**, not 6.

### 6.1 Chunking comparison (8 known-answer questions, Top-5)

| Configuration | Chunks | Article Hit@5 | Answer Hit@5 | Answer Hit@1 (= citation accuracy) | MRR | Table Answer Hit@5 |
|---|---|---|---|---|---|---|
| `fixed/150/15` | 86 | 8/8 | **7/8** | 5/8 | 0.688 | 2/3 |
| `fixed/500/50` (the original notebook setting) | 28 | 8/8 | 8/8 | 7/8 | 0.938 | 3/3 |
| `fixed/1200/120` | 14 | 8/8 | 8/8 | 6/8 | 0.875 | 3/3 |
| `recursive/800/80` | 19 | 8/8 | 8/8 | 7/8 | 0.938 | 3/3 |
| `heading/500/50` | 42 | 8/8 | 8/8 | 6/8 | 0.854 | 3/3 |
| **`heading/1000/100`** (shipped) | 30 | 8/8 | **8/8** | **8/8** | **1.000** | 3/3 |

(Excerpt. The full table has 9 rows plus a Top-3 version.)

**What it means:**
- **The two required "X/8" numbers.** The original strategy (`fixed/500/50`) and the structure-aware one (`heading/1000/100`) both score **8/8** on Answer Hit@5. At top-5 this corpus is too easy to separate them. The difference shows at rank 1: citation accuracy is 7/8 vs 8/8 and MRR is 0.938 vs 1.000. Only the tiny `fixed/150/15` drops to 7/8 at top-5.
- **Article Hit@5 is 8/8 everywhere.** With 7 articles, "found the right article" is saturated and cannot tell strategies apart. Only the chunk-level Answer Hit can (results.md section 7).
- **Chunk size matters more than overlap.** Raising overlap from 50 to 125 at size 500 left Answer Hit@5 unchanged (100% → 100%) and added 5 chunks (section 7).
- **Top-3 vs Top-5.** The only configuration that gains is `fixed/150/15`, from 5/8 to 7/8 (+2 questions). All others are already 8/8 at top-3 (section 2).

### 6.2 The retrieval that embarrassed us (section 6)

Q2, "What does a blinking red LED on the AirFiber ONT mean?", fails citation in **7 of 9 configurations**. Under `fixed/150/15` the top chunk scores 0.576 but does not contain the answer, and no chunk in the top-5 does. The diagnosis: the embedding covers the whole chunk, so a chunk that is mostly about the *subject* (the LED table header) out-scores the small chunk holding the *answer* row. Under `heading/1000/100` the whole LED table stays in one chunk, prefixed with `... > Router LED status reference`, and it ranks 1st at 0.540. The lesson in results.md: *"Chunk boundaries are a retrieval parameter, not a formatting one."*

### 6.3 Metadata filter (section 4)

| Case | Question | Filter | Unfiltered top-1 | Filtered top-1 |
|---|---|---|---|---|
| F1 | What is the 500 rupee charge for? | `installation` | KB-006 account_management.md (0.230) | KB-005 installation_setup.md (0.186) |
| F2 | How do I raise a ticket? | `troubleshooting` | KB-002 billing_faq.md (0.187) | KB-004 troubleshooting_connectivity.md (0.095) |
| F3 | What are the speed test rules? | `billing` | KB-004 troubleshooting_connectivity.md (0.553) | KB-003 refund_policy.txt (0.305) |

Filtering changed the ranking in 3 of 3 cases. Full top-5 lists with scores are in results.md. **Key insight:** filtering never raises a score. It only removes higher-scoring chunks from other areas, so the filtered top-1 is always lower. F2's filtered top score of 0.095 is **below** the 0.15 threshold, so that filtered query would be refused by the gate. A threshold tuned on unfiltered queries can refuse filtered ones.

### 6.4 Refusals and the threshold (section 5)

| ID | Question | Top-1 cosine | Who refused |
|---|---|---|---|
| O1 | What is the capital of Mongolia? | 0.060 | pre-LLM gate (no Groq call) |
| O2 | Who won the 2022 FIFA World Cup? | 0.072 | pre-LLM gate (no Groq call) |
| O3 | How do I reset my Netflix password? | 0.310 | system prompt, after a Groq call |

All 3 of 3 were refused. **Two different refusal strings appear, and that is deliberate:** `I don't know. That isn't covered in the documents I have.` is the gate, and `I don't know based on the provided documents.` is the prompt. O3 shares generic vocabulary with the corpus, so it clears the threshold, and only the prompt stops it. **The prompt layer is load-bearing, not redundant.**

**Why 0.15?** These are the threshold-sweep facts:
- The lowest top-1 score among the 8 well-formed questions is 0.424.
- The lowest among all 11 in-corpus questions (adding the 3 vaguer filter-case questions) is **0.187**.
- The highest among out-of-scope questions is **0.310**.

The two groups overlap, so **no single threshold separates them**. 0.15 is "the highest value that still keeps every in-corpus question" (11/11 kept, 2/3 out-of-scope refused before the LLM). Results.md is honest that the gate alone is weak: *"The shipped threshold of 0.15 is too low: only 2 of 3 out-of-scope questions are refused before the LLM is called."* The design accepts that and relies on the prompt for the rest. Ambiguous questions ("How do I fix it?" 0.155, "What is the charge?" 0.205) pass the gate.

### 6.5 Cited answers (section 5)

Q1 (AirFiber_1199_1M benefits), Q2 (blinking red LED) and Q3 (AF-503) were answered at temperature 0. In each, the rank-1 context chunk (`help_centre/airfiber_plans.md#1`, `troubleshooting_connectivity.md#1`, `troubleshooting_connectivity.md#2`) is the one that contains the gold answer. For example, Q3's answer says "wait 15 minutes and retry ... request a port reallocation", which matches the AF-503 row of the error-code table.

### 6.6 The decision (section 8)

**Shipped: `heading` chunking, chunk size 1000, overlap 100, Top-5.** It is the only configuration with Answer Hit@5 100%, citation accuracy 100%, MRR 1.000 and table-question Answer Hit@5 100%, and it needs 30 chunks. Size 1000 is chosen because it exceeds the largest table (740 characters), so the heading chunker never has to split a table.

---

## 7. What is NOT implemented / limitations / known gaps

- **Corpus substitution.** The brief's 6 "billing migration" articles with `ERR-4032` are not in the repo. The work uses a self-authored AirFiber corpus with `AF-xxx` codes. The method matches the brief, but the data does not.
- **No section field in the gold set.** `gold_questions.json` records article, source file and an answer substring, but not the section the brief asks for.
- **Per-question dump only for the winner.** The brief asks for the search-only dump of all 8 questions under both strategies. Results.md gives full per-question detail only for `heading/1000/100`, plus a failures-only table per configuration.
- **Citations are per answer, not per claim.** The prompt requires naming the source file. It does not require a `chunk_id` per sentence, and no code checks that each claim is supported. Chunk-level traceability comes from the `sources` list and the results.md tables.
- **Results.md "Code diff" is illustrative, not a real diff.** The helper names it shows do not exist in the code.
- **Bonus (precision vs completeness) not attempted.**
- **Re-indexing is all-or-nothing.** Every upload or delete calls `reindex()`, which re-reads, re-chunks and re-embeds **every** file in `DOCS_DIR`. That is fine for 7 articles but would be slow for a large corpus. The index also lives only in memory, so nothing is persisted between restarts except the files themselves.
- **Weak refusal gate.** As shown above, the gate catches only clearly unrelated questions. Vaguer off-topic questions reach Groq and depend on the prompt (a paid call each time).
- **Filter + threshold interaction.** Filtered queries score lower, and F2's filtered best (0.095) would be refused.
- **Small, easy evaluation.** 8 questions on 7 articles; at top-5 almost every configuration ties at 8/8. Answer Hit uses substring matching (for example `"200 Mbps"`), which can miss correct text that is formatted differently.
- **Front-matter parser is minimal.** It handles flat `key: value` lines only, with no nested YAML or lists. PDFs get metadata only from fallbacks (file stem / folder).
- **No hybrid / keyword search in Week 3.** Dense vectors can blur exact identifiers such as plan codes. Week 4 addressed this later with BM25 + reranking. It is not part of this week.

---

## 8. How to run & verify it

### Backend (from `backend/`)
Use an **arm64** Python 3.11+ on Apple Silicon. An x86_64/Rosetta interpreter resolves a torch version that is too old.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install torch && pip install -r requirements.txt
cp .env.example .env            # set GROQ_API_KEY; defaults already = heading/1000/100, TOP_K=5, 0.15
uvicorn app.main:app --reload --port 8000     # API docs at http://127.0.0.1:8000/docs
```
The first start downloads MiniLM. `GET /api/health` should show `chunk_strategy: "heading"`, `chunk_size: 1000`, `chunk_overlap: 100`, `top_k: 5`, `score_threshold: 0.15`.

### Frontend (from `frontend/`)
```bash
cd frontend && npm install && npm run dev      # http://localhost:5173 (proxies /api to :8000)
```

### Tests (no Groq calls; `conftest.py` pins heading/1000/100, TOP_K=5, 0.15 and a temp DOCS_DIR)
```bash
cd backend
pytest tests/test_chunking.py tests/test_metadata_and_chunking.py tests/test_filtering_and_refusal.py tests/test_flow.py -q
```
Expected: **51 passed** (verified while writing this guide). Running `pytest` alone runs the whole suite, including the later weeks.

### Re-run the chunking evaluation
```bash
cd backend
python scripts/evaluate_retrieval.py --no-generate   # retrieval only, no Groq
python scripts/evaluate_retrieval.py                 # also regenerates the section 5 transcripts via Groq
python scripts/chunk_size_experiment.py ../sample_documents   # notebook's 150/500/1200 sweep (prints only)
```
⚠️ `evaluate_retrieval.py` **rewrites results.md** (everything above the `<!-- week4:start -->` marker). Never hand-edit results.md. Without `--no-generate` it calls Groq.

### Demo questions (upload the `sample_documents/` folder first, leave mode on Week 3)

| Try | Expect |
|---|---|
| "What are the benefits of the AirFiber_1199_1M plan?" | Answer listing 200 Mbps etc.; top source `help_centre/airfiber_plans.md`, KB-001 |
| "What does a blinking red LED on the AirFiber ONT mean?" (table) | "Fiber cut ... raise a Line Fault ticket"; source KB-004, section "Router LED status reference" |
| "What should I do about error code AF-503?" (table) | "Exchange port is oversubscribed; wait 15 minutes and retry ..." |
| "What is the 500 rupee charge for?" with product area **unset**, then **installation** | Top source changes from KB-006 (account) to KB-005 (installation) |
| Set **Document** = `billing_faq.md`, ask "What happens if my payment fails?" | Every citation comes from that one file |
| "What is the capital of Mongolia?" | `I don't know. That isn't covered in the documents I have.` (gate, no LLM call) |
| "How do I reset my Netflix password?" | `I don't know based on the provided documents.` (prompt refusal; score ≈ 0.31 clears the gate) |

To see chunking matter, set `CHUNK_STRATEGY=fixed`, `CHUNK_SIZE=150`, `CHUNK_OVERLAP=15` in `.env`, restart, and ask the blinking-red-LED question again.

---

## 9. Files for this week

| File | Purpose |
|---|---|
| [docs/assignments/W3-Task-Set-A.md](../assignments/W3-Task-Set-A.md) | The official assignment (requirements, rubric, bonus) |
| [backend/app/services/rag_service.py](../../backend/app/services/rag_service.py) | Loading, front-matter → metadata, `build_chunks`, `VectorStore` (MiniLM + FAISS + filter), `answer_with_groq` (gate + prompt), `RagService` |
| [backend/app/services/chunking.py](../../backend/app/services/chunking.py) | `fixed`, `recursive`, `heading` strategies; table-as-one-block logic |
| [backend/app/api/chat.py](../../backend/app/api/chat.py) | `POST /api/chat`: builds `product_area` / `source` filters, maps errors to HTTP codes |
| [backend/app/api/documents.py](../../backend/app/api/documents.py) | `/api/health`, list / upload / delete documents |
| [backend/app/config.py](../../backend/app/config.py), [backend/.env.example](../../backend/.env.example) | Settings and chosen defaults (`heading`, 1000, 100, top-k 5, threshold 0.15) |
| [backend/app/schemas.py](../../backend/app/schemas.py) | Request / response models (`ChatRequest`, `ChatResponse`, ...) |
| [sample_documents/](../../sample_documents/) | The mock AirFiber help centre with YAML front-matter (KB-004 holds the 3 tables). `not_supported.bin` is for testing upload rejection |
| [backend/eval/gold_questions.json](../../backend/eval/gold_questions.json) | 8 known-answer, 2 ambiguous, 3 out-of-scope, 3 filter questions (drives sections 1–8) |
| [backend/scripts/evaluate_retrieval.py](../../backend/scripts/evaluate_retrieval.py) | Builds 9 indexes, scores them, writes results.md sections 1–8 |
| [backend/scripts/chunk_size_experiment.py](../../backend/scripts/chunk_size_experiment.py) | The notebook's original chunk-size sweep (150/500/1200, `fixed`) |
| [results.md](../../results.md) (sections 1–8) | Generated evaluation report: tables, filter lists, transcripts, decision |
| [backend/tests/test_chunking.py](../../backend/tests/test_chunking.py) | Service chunker equals the notebook splitter |
| [backend/tests/test_metadata_and_chunking.py](../../backend/tests/test_metadata_and_chunking.py) | Front-matter parsing, metadata fallbacks, 4 fields on every chunk, heading keeps a table intact while fixed splits it |
| [backend/tests/test_filtering_and_refusal.py](../../backend/tests/test_filtering_and_refusal.py) | Filter behaviour (exact, multi-value, changes ranking), gate refusals, empty-LLM fallback |
| [backend/tests/test_flow.py](../../backend/tests/test_flow.py) | End-to-end API: health, uploads (single / multi / folder / PDF / invalid), delete, chat with stubbed LLM |
| [backend/tests/conftest.py](../../backend/tests/conftest.py) | Pins config, temp DOCS_DIR, tracing off, PDF fixture |
| [frontend/src/components/molecules/ChatInput.tsx](../../frontend/src/components/molecules/ChatInput.tsx), [MessageBubble.tsx](../../frontend/src/components/molecules/MessageBubble.tsx), [frontend/src/services/api.ts](../../frontend/src/services/api.ts) | Product-area filter UI, citation rendering, all HTTP calls |
| [README.md](../../README.md), [backend/README.md](../../backend/README.md), [frontend/README.md](../../frontend/README.md), [USER_GUIDE.md](../../USER_GUIDE.md) | Setup and overview (they also describe later weeks) |

---

## 9a. Common confusions (extra)

- **Three similarly named fixtures.** `gold_questions.json` drives the Week 3 chunking eval. `golden_set.json` is the UI's one-click prompts and is not an eval fixture. `golden_set.jsonl` holds the Week 4 labels.
- **Two different defaults.** `chunking.DEFAULT_STRATEGY` is `"fixed"`, the fallback used when `build_chunks` is called without a strategy (for example by `chunk_size_experiment.py`). The **app's** default is `heading`, from `config.py`.
- **Two refusal strings.** These are not a bug. Each tells you which layer refused.
- **`score` is cosine similarity, not a probability.** It can even be negative (see the filtered lists in results.md section 4).
- **"6 articles" vs "7 articles".** The Task Set A work was done on 6. Week 4 added KB-007, and results.md was regenerated on 7.
- **`chunk_id` is positional.** It is the chunk's index within its own file (`#0`, `#1`, ...), so changing the chunking config renumbers everything.

---

## 10. Glossary

| Term | Meaning |
|---|---|
| RAG | Retrieval-Augmented Generation: fetch relevant passages, then have an LLM answer from them only |
| LLM | Large Language Model; here `openai/gpt-oss-120b` served by Groq |
| Groq | The hosted LLM provider, called through the OpenAI-compatible `openai` Python client |
| Hallucination | A fluent answer not supported by any source |
| Chunk | A small piece of a document that is embedded and retrieved as a unit |
| Chunk size / overlap | Target length of a chunk in characters / characters repeated between neighbouring chunks |
| Structure-aware chunking | Cutting along document structure (headings, tables) instead of a fixed character count |
| Embedding | A vector of numbers representing a text's meaning |
| MiniLM (`all-MiniLM-L6-v2`) | The small sentence-transformers embedding model used here |
| Cosine similarity | How closely two vectors point the same way (1 = same direction) |
| FAISS / `IndexFlatIP` | Vector search library / its exact, brute-force inner-product index |
| Top-k | Number of best chunks returned by retrieval |
| Front-matter | A `---`-delimited `key: value` block at the top of a document, used for metadata |
| Metadata filter | Restricting retrieval to chunks whose metadata matches (e.g. `product_area`) |
| `SCORE_THRESHOLD` | The minimum best cosine needed before the LLM is called (0.15) |
| Grounding prompt | The system prompt forcing context-only answers and an exact refusal sentence |
| Gold question / gold answer string | A question whose correct article and an answer substring are known in advance |
| Article Hit@k / Answer Hit@k | Right article in top-k / right article **and** answer text in top-k |
| MRR | Mean Reciprocal Rank: average of 1/rank of the first correct chunk |
| Citation accuracy | Answer Hit@1: the top cited chunk really contains the answer |
| Out-of-scope / out-of-corpus | A question the documents cannot answer and that must be refused |

---

## 11. Key takeaways

- **Chunk boundaries decide what can be found.** With `fixed/150/15` the blinking-red-LED answer never reached the top-5. With `heading/1000/100`, which keeps the table whole and adds the heading path, it is rank 1.
- **Measure at the chunk level, not the article level.** Article Hit@5 was 8/8 for all 9 configurations. Only Answer Hit, MRR and citation accuracy separated them.
- **Shipped `heading/1000/100`, Top-5**: Answer Hit@5 8/8, citation accuracy 8/8, MRR 1.000, from 30 chunks. `chunk_size` must exceed the largest table (740 characters).
- **Metadata filters work but lower scores.** They changed the top-1 in 3/3 cases. They can also push a query below the refusal threshold (F2 at 0.095).
- **Refusal needs two layers.** The 0.15 gate refuses clearly unrelated questions for free (O1, O2). The forced "say exactly ..." prompt catches the ones that slip through (O3 at 0.310).
- **A threshold tuned on clean questions lies.** The answerable minimum fell from 0.424 to 0.187 once vaguer questions were added, overlapping the off-topic maximum of 0.310.
- **Honest gaps:** no section labels in the gold set, a per-question dump only for the winner, per-answer rather than per-claim citations, full re-indexing on every upload, and no attempt at the bonus.
