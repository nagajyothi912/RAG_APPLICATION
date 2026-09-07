"""
RAG pipeline ported from untitled13.py (Colab notebook).

Kept unchanged from the notebook:
- document loaders (.txt, .md, .pdf)
- character chunking with overlap (now `chunking.chunk_fixed`, the default strategy)
- Chunk dataclass (extended with metadata fields, original three unchanged)
- SentenceTransformer embeddings (all-MiniLM-L6-v2, normalized)
- FAISS IndexFlatIP vector store
- top-k retrieval and SCORE_THRESHOLD
- Groq chat completion prompt and "I don't know" fallback

Adapted only where the notebook is Colab-specific:
- API key comes from settings instead of getpass
- files are saved from FastAPI uploads instead of google.colab.files
- load_documents walks subfolders so folder uploads work
- prints are replaced with logging; ask() returns data for the API

Added for the Week 3 retrieval evaluation (not in the notebook):
- YAML front-matter parsing into per-chunk metadata
  (source_file, article_id, product_area, last_updated)
- pluggable chunking strategies (see chunking.py)
- metadata filtering on retrieval
- citations that carry article_id and section

Added for the Week 4 retrieval upgrade (not in the notebook):
- hybrid BM25 + dense retrieval fused with Reciprocal Rank Fusion
- cross-encoder reranking of the fused candidate pool (see retrieval.py)
- RETRIEVAL_MODES: "week3" is the notebook path unchanged, "week4" adds
  the two stages above. Week 3 remains the default so the notebook
  behaviour, and every number in results.md, is still reproducible.

Added for the Week 5 error analysis (not in the notebook):
- the Groq prompt strings lifted out of answer_with_groq into module constants
  with a PROMPT_ID derived from their hash, so a trace records which prompt
  produced it and an edit cannot silently relabel old traces
- an optional `capture` out-parameter on answer_with_groq that records the
  rendered prompt, the model parameters and the raw output for a trace
- per-request tracing emitted from ask() (see tracing.py). Off by default.
  The generated request itself is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

import faiss
import numpy as np
from openai import OpenAI
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

from app.config import settings
from app.services import tracing
from app.services.chunking import DEFAULT_STRATEGY, STRATEGIES, chunk_document, chunk_fixed_text
from app.services.retrieval import (
    BM25Index,
    Scored,
    get_reranker,
    minmax,
    mmr_select,
    reciprocal_rank_fusion,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
EMBED_MODEL_NAME = settings.embed_model_name
SCORE_THRESHOLD = settings.score_threshold

METADATA_FIELDS = ("source_file", "article_id", "product_area", "last_updated")
UNCATEGORIZED = "uncategorized"

WEEK3 = "week3"
WEEK4 = "week4"
RETRIEVAL_MODES = (WEEK3, WEEK4)

# The reranker reads every candidate against the query, so the pool is kept
# small. Four times top_k with a floor of 25 gives the cross-encoder enough
# room to promote a chunk the dense top-k missed without making the call
# noticeably slower on a seven-article corpus. The floor is 25 because the
# assignment specifies a cross-encoder rerank "over the top 25"; at the shipped
# top_k of 5 the multiplier already exceeds it.
CANDIDATE_MULTIPLIER = 4
MIN_CANDIDATES = 25

# MMR is off by default. It is the bonus experiment, not the shipped retriever:
# section 15 of results.md measures what it costs at every lambda and the
# answer is that it can only push the labelled chunk down. lam = 1.0 is the
# identity, so leaving this None and passing 1.0 are the same ranking.
MMR_LAMBDA_DEFAULT = None

# Curated questions the chat UI offers. Deliberately a separate file from
# eval/gold_questions.json, which drives results.md - editing the UI list must
# not move any number in the report.
GOLDEN_SET_PATH = Path(__file__).resolve().parents[2] / "eval" / "golden_set.json"

# The Groq prompt, lifted out of answer_with_groq so a trace can record which
# prompt produced it. The strings are byte-identical to what the notebook port
# has always sent.
SYSTEM_PROMPT = (
    "Answer ONLY using the provided context. Every answer must name "
    "the source file it came from. If the context does not contain "
    "the answer, say exactly: \"I don't know based on the provided "
    "documents.\" Never use outside knowledge."
)
USER_PROMPT_TEMPLATE = "Context:\n{context}\n\nQuestion: {question}"
MAX_TOKENS = 400

# Two halves, because neither works alone. PROMPT_VERSION is hand-bumped and is
# what groups traces into before/after cohorts - a bare hash gives no ordering
# and no intent. PROMPT_SHA is derived, so the version cannot drift away from
# the strings it names: edit either template and it changes, and the test
# pinning the literal goes red. Both templates are hashed, because the user
# prompt's framing is as much a prompt choice as the system message.
PROMPT_VERSION = "v1"
PROMPT_SHA = hashlib.sha256(
    (SYSTEM_PROMPT + "\x00" + USER_PROMPT_TEMPLATE).encode("utf-8")
).hexdigest()[:12]
PROMPT_ID = f"{PROMPT_VERSION}-{PROMPT_SHA}"

# Kept as a module-level name because the notebook and the existing tests import it.
chunk_text = chunk_fixed_text


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
    article_id: str = ""
    product_area: str = UNCATEGORIZED
    last_updated: str = "unknown"
    section: str = ""
    title: str = ""

    @property
    def source_file(self) -> str:
        """Required metadata field name from the assignment; `source` is the notebook name."""
        return self.source

    def metadata(self) -> dict:
        return {
            "source_file": self.source_file,
            "article_id": self.article_id,
            "product_area": self.product_area,
            "last_updated": self.last_updated,
        }


@dataclass
class LoadedDocument:
    source: str
    text: str
    metadata: dict = field(default_factory=dict)


def _read_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _read_pdf(path: str) -> str:
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_front_matter(text: str) -> tuple[dict, str]:
    """
    Split a leading `---` YAML block off the document.

    Deliberately a flat `key: value` parser rather than a YAML dependency: the
    metadata contract is four scalar fields and nothing more.
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    meta: dict = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "\n".join(lines[index + 1 :]).lstrip("\n")
            return meta, body
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower()
            if key:
                meta[key] = value.strip().strip('"').strip("'")
    return {}, text


def derive_metadata(source: str, front_matter: dict) -> dict:
    """
    Build the four required metadata fields.

    Front-matter wins. Without it, `product_area` falls back to the top-level
    folder of the upload (so folder uploads stay filterable) and `article_id`
    falls back to the file stem, which keeps citations stable for user-supplied
    PDFs that carry no front-matter at all.
    """
    parts = source.replace("\\", "/").split("/")
    folder = parts[0] if len(parts) > 1 else ""
    stem = os.path.splitext(parts[-1])[0]

    return {
        "source_file": source,
        "article_id": front_matter.get("article_id") or stem,
        "product_area": front_matter.get("product_area") or folder or UNCATEGORIZED,
        "last_updated": front_matter.get("last_updated") or "unknown",
        "title": front_matter.get("title") or stem,
    }


def load_documents(docs_dir: str) -> List[LoadedDocument]:
    docs: List[LoadedDocument] = []
    for root, _, files in os.walk(docs_dir):
        for fname in sorted(files):
            path = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext in (".txt", ".md"):
                raw = _read_txt(path)
            elif ext == ".pdf":
                raw = _read_pdf(path)
            else:
                continue
            source = os.path.relpath(path, docs_dir)
            front_matter, body = parse_front_matter(raw)
            docs.append(
                LoadedDocument(source=source, text=body, metadata=derive_metadata(source, front_matter))
            )
    return docs


def build_chunks(
    docs_dir: str,
    chunk_size: int = 500,
    overlap: int = 50,
    strategy: str = DEFAULT_STRATEGY,
) -> List[Chunk]:
    all_chunks: List[Chunk] = []
    for doc in load_documents(docs_dir):
        pieces = chunk_document(doc.text, strategy=strategy, chunk_size=chunk_size, overlap=overlap)
        for i, piece in enumerate(pieces):
            all_chunks.append(
                Chunk(
                    text=piece.text,
                    source=doc.source,
                    chunk_id=i,
                    article_id=doc.metadata.get("article_id", ""),
                    product_area=doc.metadata.get("product_area", UNCATEGORIZED),
                    last_updated=doc.metadata.get("last_updated", "unknown"),
                    section=piece.section,
                    title=doc.metadata.get("title", ""),
                )
            )
    return all_chunks


def _matches(chunk: Chunk, filters: dict) -> bool:
    for key, wanted in filters.items():
        if wanted in (None, "", []):
            continue
        actual = getattr(chunk, key, None)
        if actual is None:
            return False
        if isinstance(wanted, (list, tuple, set)):
            if str(actual).lower() not in {str(w).lower() for w in wanted}:
                return False
        elif str(actual).lower() != str(wanted).lower():
            return False
    return True


class VectorStore:
    def __init__(self):
        self.embedder = SentenceTransformer(EMBED_MODEL_NAME)
        self.chunks: List[Chunk] = []
        self.faiss_index = None
        self.bm25: BM25Index | None = None
        self.fingerprint = tracing.corpus_fingerprint([])

    def _embed(self, texts):
        vecs = self.embedder.encode(texts, normalize_embeddings=True)
        return np.array(vecs, dtype="float32")

    def index(self, chunks: Sequence[Chunk]):
        self.chunks = list(chunks)
        # One short hash naming exactly which chunks are indexed. A trace
        # records it so a replay can tell "the corpus moved under me" from "the
        # retriever changed" - chunk ids are positional, so a rechunk silently
        # renumbers everything and a replay would otherwise produce a
        # plausible-looking but meaningless diff.
        self.fingerprint = tracing.corpus_fingerprint(self.chunks)
        if not chunks:
            self.faiss_index = None
            self.bm25 = None
            return
        vecs = self._embed([c.text for c in chunks])
        dim = vecs.shape[1]
        self.faiss_index = faiss.IndexFlatIP(dim)
        self.faiss_index.add(vecs)
        # Cheap to build and unused by Week 3, but building it here keeps the
        # two indexes over exactly the same chunk list and in the same order,
        # which is what lets fusion address chunks by position.
        self.bm25 = BM25Index([c.text for c in chunks])

    def product_areas(self) -> List[str]:
        return sorted({c.product_area for c in self.chunks if c.product_area})

    def search(self, query: str, top_k: int = 3, filters: Optional[dict] = None):
        """
        Retrieve top-k chunks, optionally restricted by chunk metadata.

        When a filter is active the FAISS search widens to the whole corpus and
        the filter is applied to the ranked list. That is exact rather than an
        over-fetch approximation: a filtered result can never be silently
        dropped because it fell outside a fixed candidate window.
        """
        if self.faiss_index is None or len(self.chunks) == 0:
            return []
        active = {k: v for k, v in (filters or {}).items() if v not in (None, "", [])}
        search_k = len(self.chunks) if active else min(top_k, len(self.chunks))
        query_vec = self._embed([query])
        scores, idxs = self.faiss_index.search(query_vec, search_k)
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx == -1:
                continue
            chunk = self.chunks[idx]
            if active and not _matches(chunk, active):
                continue
            results.append((chunk, float(score)))
            if len(results) >= top_k:
                break
        return results

    def _allowed_indices(self, filters: Optional[dict]) -> tuple[list[int], dict]:
        active = {k: v for k, v in (filters or {}).items() if v not in (None, "", [])}
        if not active:
            return list(range(len(self.chunks))), active
        return [i for i, c in enumerate(self.chunks) if _matches(c, active)], active

    def search_hybrid(
        self,
        query: str,
        top_k: int = 3,
        filters: Optional[dict] = None,
        candidate_k: Optional[int] = None,
        rerank: bool = True,
        use_keyword: bool = True,
        mmr_lambda: Optional[float] = MMR_LAMBDA_DEFAULT,
    ) -> list[tuple["Chunk", Scored]]:
        """
        Week 4 retrieval: BM25 + dense, fused by RRF, then cross-encoder reranked.

        Returns (chunk, Scored) pairs rather than (chunk, score) so every stage's
        contribution survives to the API. `search` above is left untouched -
        Week 3, the evaluation harness, and the tests that pin the exact-filter
        invariant all still go through it.

        Filtering stays exact here for the same reason it is exact there: both
        retrievers rank the whole corpus and the filter is applied to the ranked
        lists, so a matching chunk is never lost to a candidate window.

        `mmr_lambda` diversifies the final selection (see `mmr_select`). It is
        applied last, after whichever stage decided the order, so it is a
        re-selection of the candidate pool rather than a fourth scoring signal.
        None or 1.0 leaves the order exactly as it was.

        `rerank` and `use_keyword` exist so each Week 4 stage can be switched on
        alone. The assignment requires exactly one retrieval variable to differ
        between the before and after runs, and `scripts/evaluate_week4.py` uses
        these to build three arms that each differ from the dense baseline by a
        single change. Both default to True, so the shipped `week4` mode is
        unaffected.
        """
        if self.faiss_index is None or len(self.chunks) == 0:
            return []

        allowed, active = self._allowed_indices(filters)
        if not allowed:
            return []
        allowed_set = set(allowed)

        pool = candidate_k or max(top_k * CANDIDATE_MULTIPLIER, MIN_CANDIDATES)
        pool = min(pool, len(allowed))

        query_vec = self._embed([query])
        scores, idxs = self.faiss_index.search(query_vec, len(self.chunks))
        dense_scores: dict[int, float] = {}
        dense_order: list[int] = []
        for score, idx in zip(scores[0], idxs[0]):
            idx = int(idx)
            if idx == -1 or idx not in allowed_set:
                continue
            dense_scores[idx] = float(score)
            dense_order.append(idx)

        keyword_hits = self.bm25.search(query, len(self.chunks)) if (use_keyword and self.bm25) else []
        keyword_scores: dict[int, float] = {}
        keyword_order: list[int] = []
        for idx, score in keyword_hits:
            if idx not in allowed_set:
                continue
            keyword_scores[idx] = score
            keyword_order.append(idx)

        fused = reciprocal_rank_fusion(
            {"dense": dense_order[:pool], "keyword": keyword_order[:pool]}
        )
        if not fused:
            return []
        candidates = sorted(fused, key=lambda i: (fused[i], dense_scores.get(i, 0.0)), reverse=True)[:pool]

        rerank_scores = None
        if rerank:
            rerank_scores = get_reranker().score(query, [self.chunks[i].text for i in candidates])

        scored: list[Scored] = []
        for position, idx in enumerate(candidates):
            scored.append(
                Scored(
                    index=idx,
                    dense_score=dense_scores.get(idx, 0.0),
                    keyword_score=keyword_scores.get(idx, 0.0),
                    fused_score=fused[idx],
                    rerank_score=rerank_scores[position] if rerank_scores else None,
                    dense_rank=dense_order.index(idx) + 1 if idx in dense_scores else None,
                    keyword_rank=keyword_order.index(idx) + 1 if idx in keyword_scores else None,
                )
            )

        # Rerank score wins when the cross-encoder ran; otherwise the fused order
        # stands. Falling back rather than erroring is what makes a missing or
        # undownloadable reranker a quality regression instead of an outage.
        if rerank_scores:
            scored.sort(key=lambda s: s.rerank_score, reverse=True)
        else:
            scored.sort(key=lambda s: s.fused_score, reverse=True)

        if mmr_lambda is not None and mmr_lambda < 1.0:
            scored = self._apply_mmr(scored, top_k, mmr_lambda)

        return [(self.chunks[s.index], s) for s in scored[:top_k]]

    def _apply_mmr(self, scored: list[Scored], top_k: int, lam: float) -> list[Scored]:
        """
        Re-select the head of an ordered candidate list for diversity.

        Vectors come back out of the FAISS index rather than being cached on the
        store: they are normalised at index time, so an inner product between
        two reconstructed rows is already the cosine, and reconstructing a
        candidate pool of 25 costs nothing next to the query encode.
        """
        by_index = {s.index: s for s in scored}
        order = [s.index for s in scored]
        relevance = minmax(
            {s.index: (s.rerank_score if s.rerank_score is not None else s.fused_score) for s in scored}
        )
        vectors = {i: self.faiss_index.reconstruct(int(i)) for i in order}

        def similarity(a: int, b: int) -> float:
            return float(np.dot(vectors[a], vectors[b]))

        chosen = mmr_select(order, relevance, similarity, top_k, lam)
        rest = [i for i in order if i not in set(chosen)]
        return [by_index[i] for i in chosen + rest]


def format_citation(chunk: Chunk) -> str:
    bits = [f"Source: {chunk.source}"]
    if chunk.article_id:
        bits.append(f"article_id: {chunk.article_id}")
    if chunk.section:
        bits.append(f"section: {chunk.section}")
    bits.append(f"chunk #{chunk.chunk_id}")
    return "[" + ", ".join(bits) + "]"


def _cap(capture: dict | None, **fields) -> None:
    """One `if` when tracing is off, which is the common case."""
    if capture is not None:
        capture.update(fields)


def answer_with_groq(
    client: OpenAI,
    model: str,
    question: str,
    results,
    gate_score: float | None = None,
    temperature: float | None = None,
    *,
    capture: dict | None = None,
) -> str:
    """
    `gate_score` exists because Week 4 reorders the results. A cross-encoder
    logit is unbounded and not comparable to SCORE_THRESHOLD, and after
    reranking `results[0]` is no longer guaranteed to be the highest-cosine
    chunk - so the caller passes the best *dense* cosine in the returned set
    and the refusal gate keeps measuring the same quantity it always has.
    Omitted, it falls back to results[0][1], which is Week 3 unchanged.

    `temperature` is for the evaluation harness only. The app leaves it None so
    the request is byte-for-byte what it always was; `evaluate_week4.py` pins it
    to 0 so re-running the report does not silently change the generation column
    - at the default temperature the same question produced a differently-worded
    answer on each run, which is enough to move the G tally between runs.

    `capture` is the Week 5 tracing channel and is keyword-only. It is an
    out-parameter rather than a richer return type because this function's
    return value is compared against a bare refusal string by both evaluation
    scripts and six tests; widening it would break every one of them. A plain
    dict, not a dataclass, so this module needs no import from tracing.py.

    The prompt fields are written into `capture` *before* the network call, so
    a generation that fails still records the prompt that failed - which is the
    trace you most want when a request 502s.
    """
    _cap(
        capture,
        called=False,
        prompt_id=PROMPT_ID,
        prompt_version=PROMPT_VERSION,
        prompt_sha256=PROMPT_SHA,
        model=model,
        refusal=None,
    )
    if not results:
        _cap(capture, refusal="gate")
        return "I don't know. That isn't covered in the documents I have."
    top_score = results[0][1] if gate_score is None else gate_score
    if top_score < SCORE_THRESHOLD:
        _cap(capture, refusal="gate")
        return "I don't know. That isn't covered in the documents I have."

    context = "\n\n".join(f"{format_citation(c)}\n{c.text}" for c, score in results)

    system = SYSTEM_PROMPT
    prompt = USER_PROMPT_TEMPLATE.format(context=context, question=question)
    _cap(
        capture,
        called=True,
        system_prompt=system,
        user_prompt=prompt,
        user_prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        context_chars=len(context),
        params={"temperature": temperature, "max_tokens": MAX_TOKENS},
    )
    started = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=MAX_TOKENS,
        **({} if temperature is None else {"temperature": temperature}),
    )
    api_ms = (time.perf_counter() - started) * 1000

    # Every read off the response is getattr-guarded. The suite's fake clients
    # are minimal objects carrying only choices[0].message.content, and an
    # AttributeError raised here would surface to the user as a 502 from ask().
    choice = response.choices[0]
    raw = getattr(getattr(choice, "message", None), "content", None)
    usage_obj = getattr(response, "usage", None)
    _cap(
        capture,
        # Deliberately the value *before* .strip(), so an all-whitespace answer
        # is recorded as whitespace rather than as an empty string. Which of
        # the two refusal layers fired is not recoverable otherwise.
        raw_output=raw,
        finish_reason=getattr(choice, "finish_reason", None),
        usage=None
        if usage_obj is None
        else {
            "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
            "completion_tokens": getattr(usage_obj, "completion_tokens", None),
            "total_tokens": getattr(usage_obj, "total_tokens", None),
        },
        api_latency_ms=api_ms,
    )

    content = (raw or "").strip()
    if not content:
        # Groq can return empty content - observed on weak, low-similarity context.
        # Passing that through would show the user a blank answer with citations
        # attached, which reads as a confident empty claim.
        logger.warning("LLM returned an empty answer for %r; falling back to refusal", question)
        _cap(capture, refusal="empty_content")
        return "I don't know based on the provided documents."
    return content


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
        self.strategy = settings.chunk_strategy if settings.chunk_strategy in STRATEGIES else DEFAULT_STRATEGY
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

    def document_metadata(self) -> list[dict]:
        """One row per indexed document, with its metadata and chunk count."""
        counts: dict[str, int] = {}
        meta: dict[str, dict] = {}
        for chunk in self.store.chunks:
            counts[chunk.source] = counts.get(chunk.source, 0) + 1
            meta.setdefault(chunk.source, chunk.metadata())
        rows = []
        for name in self.list_documents():
            row = dict(meta.get(name, {"source_file": name, "article_id": "", "product_area": UNCATEGORIZED, "last_updated": "unknown"}))
            row["chunks"] = counts.get(name, 0)
            rows.append(row)
        return rows

    def product_areas(self) -> list[str]:
        return self.store.product_areas()

    def reindex(self) -> int:
        chunks = build_chunks(
            str(self.docs_dir),
            chunk_size=self.chunk_size,
            overlap=self.overlap,
            strategy=self.strategy,
        )
        self.store.index(chunks)
        logger.info(
            "Indexed %s chunks from %s (strategy=%s, chunk_size=%s, overlap=%s)",
            len(chunks),
            self.docs_dir,
            self.strategy,
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

    def resolve_document(self, raw_name: str) -> str | None:
        """
        Map a requested document onto the path the index actually uses.

        The UI may send either the relative path (`help_centre/billing_faq.md`)
        or just the basename, because uploads flatten folders while the sample
        corpus on disk keeps them. Returning None means "no such document", and
        the caller refuses rather than silently answering from everything.
        """
        wanted = (raw_name or "").replace("\\", "/").strip().lower()
        if not wanted:
            return None
        names = self.list_documents()
        for name in names:
            if name.lower() == wanted:
                return name
        base = wanted.rsplit("/", 1)[-1]
        matches = [n for n in names if n.rsplit("/", 1)[-1].lower() == base]
        return matches[0] if len(matches) == 1 else None

    def _week3_finds_answer(self, question: str, answer_contains: Sequence[str]) -> bool:
        """
        True when dense-only retrieval already surfaces the answer for a question.

        This is the same grading rule the Week 3 evaluation uses: a chunk counts
        only if it contains every gold answer string, because a chunk from the
        right article that was cut before the answer still cannot be answered
        from.
        """
        if not answer_contains or not self.store.chunks:
            return False
        for chunk, _score in self.store.search(question, top_k=self.top_k):
            haystack = " ".join(chunk.text.split()).lower()
            if all(" ".join(n.split()).lower() in haystack for n in answer_contains):
                return True
        return False

    def golden_questions(self) -> list[dict]:
        """
        The curated question set the chat UI offers, with each entry's document
        resolved against what is actually indexed. `available` is False when the
        backing document has been deleted, so the UI can grey the question out
        instead of offering a question that can only be refused.

        `contrast_holds` is measured against the live index rather than read off
        the fixture. A contrast question only demonstrates the Week 3 / Week 4
        split while the near-duplicate competitors that make dense retrieval
        fail are actually indexed - delete KB-007, or serve a corpus that never
        had it, and dense finds the answer at rank 1 in both modes. The badge
        has to follow the corpus, because a label that says "Week 4 only" over a
        question both modes answer teaches the reader the opposite of the truth.
        """
        if not GOLDEN_SET_PATH.exists():
            return []
        try:
            payload = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read the golden set at %s: %s", GOLDEN_SET_PATH, exc)
            return []

        rows = []
        for item in payload.get("questions", []):
            resolved = self.resolve_document(item.get("source_file", ""))
            contrast = item.get("contrast", "")
            # Only the two contrast questions pay for this extra search, and
            # only on the page load that fetches the panel.
            holds = bool(contrast) and not self._week3_finds_answer(
                item.get("question", ""), item.get("answer_contains", [])
            )
            rows.append(
                {
                    "id": item.get("id", ""),
                    "question": item.get("question", ""),
                    "source_file": resolved or item.get("source_file", ""),
                    "article_id": item.get("article_id", ""),
                    "product_area": item.get("product_area", ""),
                    "kind": item.get("kind", "prose"),
                    # A contrast question demonstrates the Week 3 / Week 4 split
                    # and only does so against the whole corpus - the UI must not
                    # scope it to its own document, which would remove the very
                    # competitors that make Week 3 fail.
                    "contrast": contrast,
                    "contrast_holds": holds,
                    "available": resolved is not None,
                }
            )
        return rows

    def retrieve(
        self,
        question: str,
        top_k: int | None = None,
        filters: Optional[dict] = None,
        mode: str = WEEK3,
    ) -> list[tuple[Chunk, Scored]]:
        """
        Retrieval for either mode, normalised to one shape.

        Week 3 goes through `search` untouched and its cosine is reported as the
        dense score with no fused or rerank score at all - an honest empty
        column in the UI is the point, since that is exactly what Week 3 lacks.
        """
        k = top_k or self.top_k
        if mode == WEEK4:
            return self.store.search_hybrid(question, top_k=k, filters=filters)
        return [
            (chunk, Scored(index=-1, dense_score=score, dense_rank=rank))
            for rank, (chunk, score) in enumerate(
                self.store.search(question, top_k=k, filters=filters), start=1
            )
        ]

    def trace_config(self) -> dict:
        """Everything a replay needs in order to rebuild this index identically."""
        reranker = get_reranker()
        return {
            "embed_model": EMBED_MODEL_NAME,
            "chunk_strategy": self.strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.overlap,
            "top_k_default": self.top_k,
            "score_threshold": SCORE_THRESHOLD,
            "docs_dir": str(self.docs_dir),
            "groq_base_url": settings.groq_base_url,
            "groq_model": settings.groq_model,
            "groq_temperature": settings.groq_temperature,
            "rerank_model": getattr(reranker, "model_name", None),
            "reranker_unavailable": bool(getattr(reranker, "unavailable", False)),
            "candidate_multiplier": CANDIDATE_MULTIPLIER,
            "min_candidates": MIN_CANDIDATES,
            "mmr_lambda": MMR_LAMBDA_DEFAULT,
            "hybrid_available": bool(self.store.bm25 and self.store.bm25.available),
            "reranker_loaded": bool(getattr(reranker, "loaded", False)),
            "prompt_id": PROMPT_ID,
            "corpus": {
                "documents": len({c.source for c in self.store.chunks}),
                "chunks": len(self.store.chunks),
                "sources": sorted({c.source for c in self.store.chunks}),
                "fingerprint": self.store.fingerprint,
            },
        }

    def ask(
        self,
        question: str,
        top_k: int | None = None,
        filters: Optional[dict] = None,
        mode: str = WEEK3,
        *,
        trace_extra: Optional[dict] = None,
    ) -> dict:
        """
        `trace_extra` is written straight onto the emitted trace record and is
        used only by the Week 5 traffic simulator, to mark which pool a trace
        came from and to assign a readable trace id. It accepts `pool`,
        `source_id` and `trace_id`, and has no effect on retrieval or
        generation.

        Tracing is emitted from here rather than from the route because this is
        the only scope where the question, every stage's score, the rendered
        prompt, the raw model output and the answer all coexist. The route sees
        only the returned dict, and route files in this app carry no RAG logic.
        HTTP-level rejections - an empty message, an unresolvable source_file -
        never reach here and are deliberately not traced: they are input
        validation and carry no retrieval or generation to analyse.
        """
        # A live request gets a uuid. The Week 5 traffic simulator passes a
        # readable, stable id instead, because every trace id in the taxonomy
        # and the open coding is quoted by a human reading the write-up.
        trace_id = (trace_extra or {}).get("trace_id") or uuid.uuid4().hex
        started_at = tracing.utc_now_iso()
        t_start = time.perf_counter()
        writer = tracing.get_trace_writer()
        # Read once into a local: a mid-request toggle must not be able to
        # produce a half-built record.
        tracing_on = writer.enabled
        capture: dict | None = {} if tracing_on else None

        results: list = []
        answer = ""
        mode_effective = mode if mode in RETRIEVAL_MODES else WEEK3
        gate_score = 0.0
        reranked = False
        failure: BaseException | None = None
        t_retrieval_ms = 0.0
        t_generation_ms = 0.0

        try:
            payload = self._ask_inner(
                question, top_k, filters, mode_effective, capture, trace_id
            )
            results = payload["_results"]
            answer = payload["answer"]
            gate_score = payload["_gate_score"]
            reranked = payload["retrieval"]["reranked"]
            t_retrieval_ms = payload["_retrieval_ms"]
            t_generation_ms = payload["_generation_ms"]
            for key in ("_results", "_gate_score", "_retrieval_ms", "_generation_ms"):
                payload.pop(key)
            # Only when a record was actually written. Handing back an id
            # that resolves to nothing is worse than handing back nothing.
            payload["trace_id"] = trace_id if tracing_on else ""
            return payload
        except BaseException as exc:  # noqa: BLE001 - re-raised in the finally-free path below
            failure = exc
            raise
        finally:
            if tracing_on:
                # A trace must never break a request. Record construction is
                # inside the guard too: a None where a str was expected must not
                # turn a good answer into a 500. Same degrade-rather-than-fail
                # posture retrieval.py takes for BM25 and the cross-encoder.
                try:
                    refusal = (capture or {}).get("refusal")
                    answer_source = (
                        "none"
                        if failure is not None
                        else {"gate": "gate_refusal", "empty_content": "empty_fallback"}.get(
                            refusal, "llm"
                        )
                    )
                    writer.write(
                        tracing.build_chat_record(
                            trace_id=trace_id,
                            started_at=started_at,
                            finished_at=tracing.utc_now_iso(),
                            question=question,
                            mode_requested=mode,
                            mode_effective=mode_effective,
                            top_k_requested=top_k,
                            top_k_effective=top_k or self.top_k,
                            filters=filters,
                            config=self.trace_config(),
                            results=results,
                            gate_score=gate_score,
                            score_threshold=SCORE_THRESHOLD,
                            hybrid=mode_effective == WEEK4
                            and bool(self.store.bm25 and self.store.bm25.available),
                            reranked=reranked,
                            answer_text=answer,
                            answer_source=answer_source,
                            capture=capture,
                            error=failure,
                            latency_ms={
                                "retrieval": t_retrieval_ms,
                                "generation": t_generation_ms,
                                "llm_api": (capture or {}).get("api_latency_ms"),
                                "total": (time.perf_counter() - t_start) * 1000,
                            },
                            include_prompts=writer.include_prompts,
                            pool=(trace_extra or {}).get("pool"),
                            source_id=(trace_extra or {}).get("source_id"),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to record trace %s: %s", trace_id, exc)

    def _ask_inner(
        self,
        question: str,
        top_k: int | None,
        filters: Optional[dict],
        mode: str,
        capture: Optional[dict],
        trace_id: str,
    ) -> dict:
        if self.store.faiss_index is None or len(self.store.chunks) == 0:
            raise NoDocumentsError(
                "No documents are indexed yet. Upload .txt, .md, or .pdf files first."
            )
        if not self.llm_configured:
            raise RagGenerationError(
                "GROQ_API_KEY is not set. Add it to backend/.env and restart the server."
            )

        t0 = time.perf_counter()
        results = self.retrieve(question, top_k=top_k, filters=filters, mode=mode)
        # Stopped before the logging loop below, which does five stderr writes
        # that must not be charged to retrieval.
        retrieval_ms = (time.perf_counter() - t0) * 1000
        logger.info("Q: %s (mode=%s, filters=%s)", question, mode, filters or {})
        for chunk, scored in results:
            preview = chunk.text.strip()[:80].replace("\n", " ")
            logger.info(
                "  [dense %.2f / rerank %s] %s (%s, chunk #%s): %s...",
                scored.dense_score,
                "n/a" if scored.rerank_score is None else f"{scored.rerank_score:.2f}",
                chunk.source,
                chunk.article_id,
                chunk.chunk_id,
                preview,
            )

        # Gate on the best dense cosine in the returned set, in both modes. After
        # reranking the first result is no longer necessarily the highest-cosine
        # one, and a cross-encoder logit is not on the same scale as
        # SCORE_THRESHOLD - so measuring anything else here would quietly
        # invalidate the threshold analysis in results.md.
        gate_score = max((s.dense_score for _, s in results), default=0.0)
        llm_results = [(chunk, s.dense_score) for chunk, s in results]

        t1 = time.perf_counter()
        try:
            answer = answer_with_groq(
                self.client,
                settings.groq_model,
                question,
                llm_results,
                gate_score=gate_score,
                temperature=settings.groq_temperature,
                capture=capture,
            )
        except Exception as exc:
            raise RagGenerationError(f"The language model failed to generate an answer: {exc}") from exc
        finally:
            generation_ms = (time.perf_counter() - t1) * 1000

        sources = [
            {
                "source": chunk.source,
                "chunk_id": chunk.chunk_id,
                # `score` stays the dense cosine so existing clients and the
                # citation UI keep reading the same number they always have.
                "score": round(scored.dense_score, 4),
                "preview": chunk.text.strip()[:180],
                "article_id": chunk.article_id,
                "product_area": chunk.product_area,
                "last_updated": chunk.last_updated,
                "section": chunk.section,
                "dense_score": round(scored.dense_score, 4),
                "keyword_score": round(scored.keyword_score, 4),
                "fused_score": round(scored.fused_score, 6),
                "rerank_score": None if scored.rerank_score is None else round(scored.rerank_score, 4),
                "dense_rank": scored.dense_rank,
                "keyword_rank": scored.keyword_rank,
                "retriever": scored.retriever if mode == WEEK4 else "dense",
            }
            for chunk, scored in results
        ]
        reranked = any(s.rerank_score is not None for _, s in results)
        return {
            "answer": answer,
            "sources": sources,
            "mode": mode,
            "retrieval": {
                "mode": mode,
                "top_k": top_k or self.top_k,
                "hybrid": mode == WEEK4 and bool(self.store.bm25 and self.store.bm25.available),
                "reranked": reranked,
                "gate_score": round(gate_score, 4),
                "score_threshold": SCORE_THRESHOLD,
                "refused": gate_score < SCORE_THRESHOLD,
            },
            # Underscore keys are stripped by ask() before the dict reaches the
            # route; they exist only to hand the trace what the response omits.
            "_results": results,
            "_gate_score": gate_score,
            "_retrieval_ms": retrieval_ms,
            "_generation_ms": generation_ms,
        }

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
