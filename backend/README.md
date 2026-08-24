# Backend

FastAPI service for upload, indexing, and chat. RAG logic lives in `app/services/rag_service.py`. HTTP routes only call that service.

## Why PyTorch is installed

PyTorch is **not** used to serve APIs. FastAPI handles `/api/documents/upload` and `/api/chat`.

The original notebook embeds chunks with `sentence-transformers` (`all-MiniLM-L6-v2`). That library runs on PyTorch, so pip installs torch as a dependency of the embedder.

| Piece | Role |
| --- | --- |
| FastAPI | HTTP APIs |
| sentence-transformers + PyTorch | Turn text chunks into vectors |
| FAISS | Search those vectors |
| Groq | Generate the answer from retrieved chunks |

Install the **CPU** torch wheel unless you already have a CUDA build. Otherwise pip may pull a multi-GB GPU stack.

## How to run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env
```

Set `GROQ_API_KEY` in `.env` (required for chat). Then:

```bash
uvicorn app.main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs

The first start downloads the MiniLM model from Hugging Face.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Status and whether Groq is configured |
| `GET` | `/api/documents` | Indexed files and chunk count |
| `POST` | `/api/documents/upload` | Multipart `files` (one file, many files, or a folder) |
| `DELETE` | `/api/documents?name=` | Remove an indexed file and rebuild the index |
| `POST` | `/api/chat` | `{ "message": "..." }` → `{ "answer", "sources" }` |

Supported uploads: `.txt`, `.md`, `.pdf`.
