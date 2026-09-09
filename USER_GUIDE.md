# Ask My Documents — Comprehensive User Guide & System Architecture

Welcome to **Ask My Documents**, an enterprise-grade Retrieval-Augmented Generation (RAG) platform designed to answer questions strictly from your uploaded knowledge base. 

This document provides a complete, user-friendly breakdown of how the application works, how to use all features, the architecture behind its retrieval engines, and troubleshooting advice.

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Key Capabilities & Features](#key-capabilities--features)
3. [System Architecture & Data Flow](#system-architecture--data-flow)
4. [Step-by-Step User Instructions](#step-by-step-user-instructions)
   - [Starting the Application](#starting-the-application)
   - [Uploading & Managing Knowledge Base Documents](#uploading--managing-knowledge-base-documents)
   - [Asking Questions & Viewing Citations](#asking-questions--viewing-citations)
   - [Using Metadata & Product Area Filters](#using-metadata--product-area-filters)
   - [Using the Golden Question Set](#using-the-golden-question-set)
5. [Understanding Retrieval Modes: Week 3 vs. Week 4](#understanding-retrieval-modes-week-3-vs-week-4)
6. [Anti-Hallucination & Two-Layer Refusal System](#anti-hallucination--two-layer-refusal-system)
7. [Chunking Strategies Deep-Dive](#chunking-strategies-deep-dive)
8. [Configuration Reference (`.env`)](#configuration-reference-env)
9. [Evaluation & Empirical Insights](#evaluation--empirical-insights)
10. [Troubleshooting & Frequently Asked Questions](#troubleshooting--frequently-asked-questions)

---

## 1. Executive Summary

**Ask My Documents** is designed around a zero-hallucination philosophy: **The system ONLY answers questions using content present in the uploaded documents.** 

If an answer cannot be verified from the knowledge base, the application explicitly refuses to answer rather than relying on LLM internal knowledge or making up information. Every valid answer includes precise document and section citations.

### Primary Use Cases
* **Customer Support & Help Desks**: Querying internal knowledge base articles, troubleshooting guides, billing FAQs, and service plans.
* **Policy & Operations Reference**: Querying refund policies, account management terms, and operational manuals.
* **Document QA**: Uploading custom PDF, Markdown (`.md`), or text (`.txt`) documents and interrogating them with high confidence.

---

## 2. Key Capabilities & Features

* **Multi-Format Ingestion**: Supports `.pdf`, `.md`, and `.txt` files with dynamic metadata extraction (YAML front-matter).
* **Dual-Engine Retrieval**:
  * **Week 3 Engine (Dense Only)**: Semantic vector similarity using `all-MiniLM-L6-v2` embeddings and FAISS index.
  * **Week 4 Engine (Hybrid Stack)**: BM25 keyword search + Dense FAISS vector search combined via Reciprocal Rank Fusion (RRF), re-scored by an `ms-marco-MiniLM-L-6-v2` Cross-Encoder.
* **Two-Layer Anti-Hallucination Safeguard**:
  * **Algorithmic Refusal Gate**: Short-circuits queries scoring below cosine threshold (`SCORE_THRESHOLD = 0.15`).
  * **System Prompt Guard**: Enforces LLM refusal when retrieved context lacks sufficient evidence.
* **Granular Scoping & Metadata Filtering**: Filter queries by single document or product area (e.g., `plans`, `billing`, `troubleshooting`, `installation`, `account`).
* **Table-Preserving Chunking**: Specialized Markdown section-aware chunking (`heading`) that keeps technical troubleshooting tables intact.
* **Interactive One-Click Golden Questions**: Pre-loaded curated test set including explicit demonstration prompts (`G13`/`G14`) that highlight the superiority of hybrid retrieval over dense-only search.

---

## 3. System Architecture & Data Flow

The application is structured into a modern decoupled architecture:

```
┌────────────────────────────────────────────────────────┐
│             React + TypeScript Frontend                │
│  (Modern UI, Chat Panel, Retrieval Controls, Filter)  │
└───────────────────────────┬────────────────────────────┘
                            │ HTTP API Calls (services/api.ts)
                            ▼
┌────────────────────────────────────────────────────────┐
│                   FastAPI Backend                      │
│      (app/main.py, app/api/chat.py, documents.py)      │
└───────────────────────────┬────────────────────────────┘
                            │ Internal Service Layer
                            ▼
┌────────────────────────────────────────────────────────┐
│                  RagService Singleton                  │
│       (backend/app/services/rag_service.py)           │
├───────────────────────────┬────────────────────────────┤
│  Chunking Engine          │  Retrieval Engine          │
│  (services/chunking.py)   │  (services/retrieval.py)   │
│  Fixed / Recursive /      │  BM25 + FAISS (Dense)      │
│  Heading                  │  RRF Fusion & Reranker     │
└───────────────────────────┴────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
┌───────────────────────────┐ ┌──────────────────────────┐
│   FAISS Vector Index &    │ │    Groq Cloud API        │
│   MiniLM Embeddings       │ │  (Generation & Refusal) │
└───────────────────────────┘ └──────────────────────────┘
```

### Document Processing Lifecycle

1. **Ingestion & Metadata Extraction**: Uploaded files land in `DOCS_DIR`. YAML front-matter (if present) is parsed into `source_file`, `article_id`, `product_area`, and `last_updated`. Unstructured uploads automatically derive default metadata.
2. **Chunking**: Text is split into chunks using the configured strategy (`heading` strategy is recommended and default).
3. **Indexing**: Chunks are embedded with `sentence-transformers/all-MiniLM-L6-v2` and indexed into FAISS RAM vector index.
4. **Retrieval**: Upon query submission, chunks are retrieved via Week 3 (Dense cosine) or Week 4 (Hybrid BM25 + Dense RRF + Cross-Encoder Rerank).
5. **Refusal Verification**: Top retrieval candidate is evaluated against `SCORE_THRESHOLD` (0.15). If below threshold, execution stops with a refusal response.
6. **Prompt Assembly & LLM Generation**: If verified, context + citations are sent to Groq (`openai/gpt-oss-120b`), generating a response grounded strictly in context.

---

## 4. Step-by-Step User Instructions

### Starting the Application

#### 1. Backend Startup
Ensure you have Python 3.11+ (Apple Silicon arm64 recommended for macOS) and a valid `GROQ_API_KEY` set in `backend/.env`.

```bash
cd backend
# Activate your virtual environment
source .venv/bin/activate
# Start FastAPI server
uvicorn app.main:app --reload --port 8000
```
*API documentation is available at `http://127.0.0.1:8000/docs`.*

#### 2. Frontend Startup
Open a new terminal window:

```bash
cd frontend
npm run dev
```
*Access the user interface at `http://localhost:5173`.*

---

### Uploading & Managing Knowledge Base Documents

1. Open the web interface in your browser (`http://localhost:5173`).
2. Locate the **Knowledge Base** sidebar on the left.
3. Click **Upload Files** or drag and drop supported files (`.pdf`, `.md`, `.txt`).
4. To test with sample data, upload the files located in the `sample_documents/` repository folder:
   - `help_centre/airfiber_plans.md` (KB-001)
   - `help_centre/billing_faq.md` (KB-002)
   - `policies/refund_policy.txt` (KB-003)
   - `help_centre/troubleshooting_connectivity.md` (KB-004)
   - `help_centre/installation_setup.md` (KB-005)
   - `policies/account_management.md` (KB-006)
   - `help_centre/airfiber_legacy_plans.md` (KB-007)
5. You can view indexed documents, total chunk counts, product areas, and delete documents directly from the sidebar.

---

### Asking Questions & Viewing Citations

1. Type your question into the chat message box at the bottom.
2. Click **Send** or press `Enter`.
3. View the generated response in the chat window.
4. **Inspecting Citations**: Each response includes collapsible **Sources & Citations**:
   - Shows the exact source file and section.
   - Shows document `article_id` and metadata.
   - Expand the citation box to inspect the exact text snippet and confidence scores.

---

### Using Metadata & Product Area Filters

You can scope your search to specific areas to refine accuracy and avoid cross-topic confusion:

* **Document Scope Filter**: Click the **Document** dropdown in the chat input toolbar to scope search strictly to a single document (e.g. `billing_faq.md`).
* **Product Area Filter**: Select a specific area (e.g., `billing`, `installation`, `troubleshooting`, `plans`).
* *Example*: Asking *"What is the 500 rupee charge for?"* with the `installation` area selected will return the installation charge from KB-005, whereas asking without a filter may return relocation charges from KB-006.

---

### Using the Golden Question Set

Under the chat box, expand **Golden set of questions** to try 14 pre-formulated test prompts:
* Includes standard prose questions, table queries, and out-of-scope prompts.
* **Demonstrating Week 3 vs Week 4**:
  - Ask **G13** (*"Are OTT add-on charges refundable?"*) or **G14** (*"What is the fair usage limit for AirFiber_1199_1M?"*) in **Week 3** mode.
  - Notice that Week 3 dense retrieval is out-ranked by distractor legacy plans and returns *"I don't know based on the provided documents"*.
  - Switch to **Week 4 (Hybrid)** mode and ask the same question: the system retrieves the correct plan details and answers with full accuracy!

---

## 5. Understanding Retrieval Modes: Week 3 vs. Week 4

| Feature | Week 3 Mode (Notebook Baseline) | Week 4 Mode (Advanced Hybrid Stack) |
| :--- | :--- | :--- |
| **Retrieval Strategy** | Dense vector similarity (`FAISS` + `all-MiniLM-L6-v2`) | Hybrid: BM25 Lexical + Dense FAISS fused with RRF |
| **Reranking** | None | Cross-Encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) |
| **Exact Token Matching** | Moderate (smears rare identifiers like `AF-511`) | **Superior** (BM25 IDF isolates exact token codes) |
| **Latency** | Extremely Fast (~8 ms) | Fast (~150–160 ms due to Cross-Encoder) |
| **Best Used For** | Standard natural language semantic queries | Complex queries with exact product codes, IDs, or model numbers |

> [!NOTE]
> **Why Hybrid BM25 + RRF Wins**: When near-duplicate product identifiers exist in the corpus (e.g., `AirFiber_1199_1M` vs legacy plan identifiers), dense vectors alone can confuse similar plan descriptions. BM25 keyword matching scores exact term occurrences heavily, lifting the true target chunk into the reranker pool.

---

## 6. Anti-Hallucination & Two-Layer Refusal System

To eliminate hallucinated answers, **Ask My Documents** deploys two independent refusal layers:

```
User Question
      │
      ▼
┌────────────────────────┐
│  Retrieval Engine      │
└──────────┬─────────────┘
           │ Top Chunk Cosine Score
           ▼
     Is Score ≥ 0.15?
    /                \
  NO                  YES
  │                    │
  ▼                    ▼
[Layer 1 Refusal]    ┌────────────────────────┐
"I don't know.       │  Groq LLM Generation   │
That isn't covered   │  with Strict Context   │
in the documents     └──────────┬─────────────┘
I have."                        │
                                ▼
                       Does Context Answer?
                      /                    \
                    NO                      YES
                    │                        │
                    ▼                        ▼
          [Layer 2 Refusal]             Answer +
          "I don't know based on       Citations
          the provided documents."
```

1. **Layer 1 (Algorithmic Gate)**: If the highest cosine score in the retrieved pool is lower than `SCORE_THRESHOLD` (default `0.15`), the application returns a refusal immediately without making an LLM API call.
2. **Layer 2 (System Prompt Guard)**: If a query clears the threshold (e.g. "How do I reset my Netflix password?" scores ~0.31 due to generic security terms), the context is sent to the LLM. The system prompt restricts the LLM to context-only knowledge, causing it to respond with *"I don't know based on the provided documents."*

---

## 7. Chunking Strategies Deep-Dive

Three configurable chunking strategies are available in `backend/app/services/chunking.py`:

| Strategy | Algorithm & Behavior | Table & Structure Preservation | Recommended Use |
| :--- | :--- | :--- | :--- |
| `fixed` | Fixed character window sliding with whitespace collapsing. | Low (Can split table headers from rows). | Baseline comparisons. |
| `recursive` | Hierarchical splitting (Paragraphs → Lines → Sentences → Words). | Moderate. | Generic un-structured text. |
| **`heading`** *(Default)* | Markdown section-aware splitting. Prefixes sections with heading hierarchy. | **High** (Keeps tables complete). | **Production Default**. |

> [!IMPORTANT]
> **Table Integrity Constraint**: Troubleshooting tables (such as the ONT LED indicator table in `troubleshooting_connectivity.md`) require at least 1,000 characters per chunk (`CHUNK_SIZE=1000`). If chunk size is reduced below 750 characters, table headers become separated from data rows, degrading citation and answer accuracy.

---

## 8. Configuration Reference (`.env`)

Configure the application by modifying `backend/.env`:

| Setting | Default Value | Description |
| :--- | :--- | :--- |
| `GROQ_API_KEY` | *Required* | API key for Groq LLM access. |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | OpenAI-compatible API endpoint for Groq. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | LLM model deployed for text generation. |
| `EMBED_MODEL_NAME` | `all-MiniLM-L6-v2` | SentenceTransformers embedding model. |
| `CHUNK_STRATEGY` | `heading` | Active chunking strategy (`heading`, `recursive`, `fixed`). |
| `CHUNK_SIZE` | `1000` | Target character count per chunk. |
| `CHUNK_OVERLAP` | `100` | Character overlap between consecutive chunks. |
| `TOP_K` | `5` | Number of candidate chunks retrieved for generation. |
| `SCORE_THRESHOLD` | `0.15` | Cosine similarity threshold for Layer 1 refusal. |
| `DOCS_DIR` | `data/docs` | Directory where uploaded files are stored. |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed CORS origins for the frontend application. |

---

## 9. Evaluation & Empirical Insights

The repository includes an empirical evaluation suite (`evaluate_retrieval.py` and `evaluate_week4.py`) generating `results.md`:

* **Chunking Benchmark**: `heading/1000/100` achieved **100% Answer Hit@5** and **100% Citation Accuracy** on test suites.
* **Corpus-Dependent Retrieval Decisions**: 
  - On a small 6-article corpus, BM25 keyword matching offered no gain over dense search.
  - Upon adding `airfiber_legacy_plans.md` (KB-007) containing near-duplicate plan codes, **Week 4 (BM25 + RRF)** improved **Hit@1 accuracy from 66.7% to 75.0%** and **MRR from 0.788 to 0.819**.
* **MMR (Maximal Marginal Relevance) Evaluation**: MMR diversity re-ranking was benchmarked but **not shipped**, as it forced valid single-source answer chunks out of the top-K without improving answer accuracy.

---

## 10. Troubleshooting & Frequently Asked Questions

### Q1: The backend fails with PyTorch errors on macOS Apple Silicon.
* **Cause**: Incorrect PyTorch build installed via Rosetta x86 emulation.
* **Fix**: Ensure your Python interpreter is native `arm64` (`/opt/homebrew/bin/python3`). Recreate virtual environment using arm64 Python.

### Q2: Why does the system say "I don't know based on the provided documents" for a question I think is answered?
* **Check Filters**: Verify whether a **Document** or **Product Area** filter is active in the chat input.
* **Check Retrieval Mode**: Try toggling between **Week 3** and **Week 4** mode.
* **Inspect Chunk Size**: Ensure `CHUNK_SIZE` in `.env` is set to `1000` so relevant sections aren't split mid-sentence.

### Q3: How do I clear the indexed documents?
* You can delete individual documents via the UI sidebar trash icons, or stop the server, delete files in `backend/data/docs/`, and restart the backend.

### Q4: Can I run without a Groq API key?
* The backend will start and retrieval search can be evaluated via evaluation scripts, but live chat generation requires a valid `GROQ_API_KEY`.

---
*Document Version: 1.0.0 — Ask My Documents Project*
