# Ask My Documents

RAG app: upload documents, ask questions, get answers **only from those files**, with sources. If the answer is not in the documents, the app says it does not know.

Pipeline comes from `untitled13.py`: load `.txt` / `.md` / `.pdf`, chunk, MiniLM embeddings, FAISS search, **Groq** generation.

```text
React (TypeScript)  →  FastAPI  →  rag_service.py  →  FAISS + Groq
```

- **Frontend:** upload + chat UI. HTTP only in `frontend/src/services/api.ts`.
- **Backend:** FastAPI routes. No RAG code in the route files.
- **RAG service:** notebook logic (chunk, embed, retrieve, Groq).

PyTorch is only the runtime for MiniLM embeddings (`sentence-transformers`). It is not the web framework. See `backend/README.md`.

## How to run

1. Backend: [backend/README.md](backend/README.md)
2. Frontend: [frontend/README.md](frontend/README.md)

You need Python 3.11+, Node.js 18+, and a Groq API key in `backend/.env` as `GROQ_API_KEY`.

## Environment

Copy `backend/.env.example` to `backend/.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | empty | Groq API key (required for chat) |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Groq OpenAI-compatible endpoint |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Chat model |
| `EMBED_MODEL_NAME` | `all-MiniLM-L6-v2` | Embedding model |
| `CHUNK_SIZE` | `500` | Character chunk size |
| `CHUNK_OVERLAP` | `50` | Chunk overlap |
| `TOP_K` | `3` | Retrieved chunks |
| `SCORE_THRESHOLD` | `0.08` | Below this, the app says it does not know |
| `DOCS_DIR` | `data/docs` | Uploaded files |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed UI origins |

## RAG flow

1. Load `.txt`, `.md`, `.pdf`
2. Chunk (500 / 50 overlap)
3. Embed with MiniLM
4. Index in FAISS `IndexFlatIP`
5. Retrieve top-K
6. If best score &lt; 0.08 → *I don't know. That isn't covered in the documents I have.* Otherwise Groq answers from context and names the source.

## Try it

Upload files from `sample_documents/`, then:

- In-corpus: “What are the benefits of AirFiber_1199_1M plan”
- Out-of-corpus: “What is the capital of Mongolia?”
