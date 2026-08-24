"""
RAG pipeline ported from untitled13.py (Colab notebook).

Kept unchanged from the notebook:
- document loaders (.txt, .md, .pdf)
- character chunking with overlap
- Chunk dataclass
- SentenceTransformer embeddings (all-MiniLM-L6-v2, normalized)
- FAISS IndexFlatIP vector store
- top-k retrieval and SCORE_THRESHOLD
- Groq chat completion prompt and "I don't know" fallback

Adapted only where the notebook is Colab-specific:
- API key comes from settings instead of getpass
- files are saved from FastAPI uploads instead of google.colab.files
- load_documents walks subfolders so folder uploads work
- prints are replaced with logging; ask() returns data for the API
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

import faiss
import numpy as np
from openai import OpenAI
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

from app.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
EMBED_MODEL_NAME = settings.embed_model_name
SCORE_THRESHOLD = settings.score_threshold


class RagError(Exception):
    """Base error for the RAG service."""


class NoDocumentsError(RagError):
    """Raised when a question is asked before anything is indexed."""


class RagGenerationError(RagError):
    """Raised when the LLM call fails."""


@dataclass
class Chunk:
    text: str
    source: str
    chunk_id: int


def _read_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _read_pdf(path: str) -> str:
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def load_documents(docs_dir: str):
    docs = []
    for root, _, files in os.walk(docs_dir):
        for fname in sorted(files):
            path = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext in (".txt", ".md"):
                text = _read_txt(path)
            elif ext == ".pdf":
                text = _read_pdf(path)
            else:
                continue
            source = os.path.relpath(path, docs_dir)
            docs.append((source, text))
    return docs


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
        if start <= 0:
            break
    return chunks


def build_chunks(docs_dir: str, chunk_size: int = 500, overlap: int = 50) -> List[Chunk]:
    all_chunks = []
    for filename, text in load_documents(docs_dir):
        for i, piece in enumerate(chunk_text(text, chunk_size, overlap)):
            all_chunks.append(Chunk(text=piece, source=filename, chunk_id=i))
    return all_chunks


class VectorStore:
    def __init__(self):
        self.embedder = SentenceTransformer(EMBED_MODEL_NAME)
        self.chunks = []
        self.faiss_index = None

    def _embed(self, texts):
        vecs = self.embedder.encode(texts, normalize_embeddings=True)
        return np.array(vecs, dtype="float32")

    def index(self, chunks):
        self.chunks = chunks
        if not chunks:
            self.faiss_index = None
            return
        vecs = self._embed([c.text for c in chunks])
        dim = vecs.shape[1]
        self.faiss_index = faiss.IndexFlatIP(dim)
        self.faiss_index.add(vecs)

    def search(self, query: str, top_k: int = 3):
        if self.faiss_index is None or len(self.chunks) == 0:
            return []
        query_vec = self._embed([query])
        scores, idxs = self.faiss_index.search(query_vec, top_k)
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx == -1:
                continue
            results.append((self.chunks[idx], float(score)))
        return results


def answer_with_groq(client: OpenAI, model: str, question: str, results) -> str:
    if not results or results[0][1] < SCORE_THRESHOLD:
        return "I don't know. That isn't covered in the documents I have."

    context = "\n\n".join(
        f"[Source: {c.source}, chunk #{c.chunk_id}]\n{c.text}"
        for c, score in results
    )

    system = (
        "Answer ONLY using the provided context. Every answer must name "
        "the source file it came from. If the context does not contain "
        "the answer, say exactly: \"I don't know based on the provided "
        "documents.\" Never use outside knowledge."
    )
    prompt = f"Context:\n{context}\n\nQuestion: {question}"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=400,
    )

    return response.choices[0].message.content


def sanitize_relative_path(raw: str) -> str:
    raw = (raw or "").replace("\\", "/").strip()
    parts = [part for part in raw.split("/") if part not in ("", ".", "..")]
    if not parts:
        raise ValueError("Invalid filename")
    return "/".join(parts)


class RagService:
    """FastAPI-facing wrapper around the notebook RAG pipeline."""

    def __init__(self) -> None:
        self.docs_dir = Path(settings.resolved_docs_dir)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.chunk_size = settings.chunk_size
        self.overlap = settings.chunk_overlap
        self.top_k = settings.top_k
        self.store = VectorStore()
        self.client = None
        if settings.api_key:
            self.client = OpenAI(api_key=settings.api_key, base_url=settings.groq_base_url)
        self.reindex()

    @property
    def llm_configured(self) -> bool:
        return self.client is not None and bool(settings.api_key)

    def list_documents(self) -> list[str]:
        names = []
        for root, _, files in os.walk(self.docs_dir):
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    names.append(os.path.relpath(os.path.join(root, fname), self.docs_dir))
        return sorted(names)

    def reindex(self) -> int:
        chunks = build_chunks(
            str(self.docs_dir),
            chunk_size=self.chunk_size,
            overlap=self.overlap,
        )
        self.store.index(chunks)
        logger.info(
            "Indexed %s chunks from %s (chunk_size=%s, overlap=%s)",
            len(chunks),
            self.docs_dir,
            self.chunk_size,
            self.overlap,
        )
        return len(chunks)

    def ingest_uploads(self, files: list[tuple[str, bytes]]) -> dict:
        uploaded: list[str] = []
        skipped: list[dict] = []

        for raw_name, content in files:
            try:
                relative = sanitize_relative_path(raw_name)
            except ValueError:
                skipped.append({"filename": raw_name or "(unnamed)", "reason": "Invalid filename"})
                continue

            ext = os.path.splitext(relative)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                skipped.append(
                    {
                        "filename": relative,
                        "reason": f"Unsupported file type '{ext or 'unknown'}'. Allowed: .txt, .md, .pdf",
                    }
                )
                continue

            if not content:
                skipped.append({"filename": relative, "reason": "File is empty"})
                continue

            dest = self.docs_dir / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            uploaded.append(relative)

        if not uploaded and not self.list_documents():
            return {
                "uploaded": uploaded,
                "skipped": skipped,
                "indexed_chunks": 0,
                "documents": [],
            }

        indexed_chunks = self.reindex()
        return {
            "uploaded": uploaded,
            "skipped": skipped,
            "indexed_chunks": indexed_chunks,
            "documents": self.list_documents(),
        }

    def ask(self, question: str, top_k: int | None = None) -> dict:
        if self.store.faiss_index is None or len(self.store.chunks) == 0:
            raise NoDocumentsError(
                "No documents are indexed yet. Upload .txt, .md, or .pdf files first."
            )
        if not self.llm_configured:
            raise RagGenerationError(
                "GROQ_API_KEY is not set. Add it to backend/.env and restart the server."
            )

        results = self.store.search(question, top_k=top_k or self.top_k)
        logger.info("Q: %s", question)
        for chunk, score in results:
            preview = chunk.text.strip()[:80].replace("\n", " ")
            logger.info(
                "  [%.2f] %s (chunk #%s): %s...",
                score,
                chunk.source,
                chunk.chunk_id,
                preview,
            )

        try:
            answer = answer_with_groq(self.client, settings.groq_model, question, results)
        except Exception as exc:
            raise RagGenerationError(f"The language model failed to generate an answer: {exc}") from exc

        sources = [
            {
                "source": chunk.source,
                "chunk_id": chunk.chunk_id,
                "score": round(score, 4),
                "preview": chunk.text.strip()[:180],
            }
            for chunk, score in results
        ]
        return {"answer": answer, "sources": sources}

    def delete_document(self, raw_name: str) -> dict:
        try:
            relative = sanitize_relative_path(raw_name)
        except ValueError as exc:
            raise FileNotFoundError(str(exc)) from exc

        dest = (self.docs_dir / relative).resolve()
        docs_root = self.docs_dir.resolve()
        if not dest.is_relative_to(docs_root) or not dest.is_file():
            raise FileNotFoundError(f"Document not found: {relative}")

        dest.unlink()
        parent = dest.parent
        while parent != docs_root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

        indexed_chunks = self.reindex()
        return {
            "documents": self.list_documents(),
            "indexed_chunks": indexed_chunks,
        }

    def reset_store(self) -> None:
        if self.docs_dir.exists():
            shutil.rmtree(self.docs_dir)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.reindex()


_rag_service: RagService | None = None


def get_rag_service() -> RagService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RagService()
    return _rag_service
