"""
Week 4 retrieval: hybrid (BM25 + dense) fusion and cross-encoder reranking.

Week 3 — the notebook pipeline in rag_service.py — is dense-only: embed the
query, take the FAISS top-k by cosine similarity, stop. That is one ranking
signal, and it has a known blind spot on this corpus: exact tokens. "AF-511"
and "AirFiber_1199_1M" are rare strings that MiniLM smears into a generic
"error code" / "plan name" neighbourhood, so a question naming one can rank a
sibling table row above the row that actually answers it.

Week 4 adds two stages:

1. Hybrid retrieval. BM25 scores the same chunks on lexical overlap, where a
   rare token like "AF-511" carries a high IDF and dominates. The two ranked
   lists are combined with Reciprocal Rank Fusion, which merges by *rank*
   rather than score, so BM25's unbounded scores and cosine's 0..1 range never
   have to be normalised against each other.

2. Cross-encoder reranking. The fused candidate pool (larger than top_k) is
   re-scored by cross-encoder/ms-marco-MiniLM-L-6-v2, which reads the query and
   the chunk *together* rather than comparing two independently-built vectors.
   It is far more accurate and far more expensive, which is exactly why it runs
   on a shortlist instead of the whole corpus.

Both stages degrade rather than fail. If rank_bm25 is missing, hybrid falls
back to dense-only; if the cross-encoder cannot be downloaded, the fused order
stands. `availability()` reports which stages are live so /health can say so
instead of silently answering in a weaker mode than the UI claims.

Scoring note that matters for the refusal gate: a cross-encoder score is an
unbounded logit, not a cosine similarity. It is NOT comparable to
SCORE_THRESHOLD. The gate stays on dense cosine in both modes (see
`RagService.ask`) so the "I don't know" guarantee and the threshold analysis in
results.md remain valid; the rerank score is carried alongside for display.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# RRF's smoothing constant. 60 is the value from the original Cormack et al.
# paper and the usual default; it flattens the contribution of the very top
# ranks so one retriever cannot single-handedly decide the fused order.
RRF_K = 60

_TOKEN = re.compile(r"[a-z0-9]+")

try:  # optional dependency - hybrid degrades to dense-only without it
    from rank_bm25 import BM25Okapi

    BM25_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only on a partial install
    BM25Okapi = None  # type: ignore[assignment]
    BM25_AVAILABLE = False


def tokenize(text: str) -> list[str]:
    """
    Lowercase alphanumeric tokens, with embedded identifiers also split apart.

    "AF-511" yields ["af", "511", "af511"] and "AirFiber_1199_1M" yields
    ["airfiber", "1199", "1m", "airfiber11991m"]. Keeping both the parts and
    the joined form means a question can match whether the user typed the
    identifier with punctuation or without.
    """
    lowered = text.lower()
    tokens = _TOKEN.findall(lowered)
    for match in re.finditer(r"[a-z0-9]+(?:[-_][a-z0-9]+)+", lowered):
        joined = match.group(0).replace("-", "").replace("_", "")
        if joined:
            tokens.append(joined)
    return tokens


class BM25Index:
    """Lexical index over the same chunk list the FAISS index holds."""

    def __init__(self, texts: Sequence[str]) -> None:
        self.available = BM25_AVAILABLE and len(texts) > 0
        self._bm25 = None
        if self.available:
            corpus = [tokenize(t) for t in texts]
            # rank_bm25 divides by average document length, which is zero if
            # every document tokenizes to nothing.
            if any(corpus):
                self._bm25 = BM25Okapi(corpus)
            else:
                self.available = False

    def search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        if self._bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)
        return [(idx, float(score)) for idx, score in ranked[:top_k] if score > 0.0]


def reciprocal_rank_fusion(
    rankings: dict[str, Sequence[int]],
    rrf_k: int = RRF_K,
) -> dict[int, float]:
    """
    Fuse several ranked id lists into one score per id.

    Each list contributes 1 / (rrf_k + rank). Rank-based fusion is the point:
    BM25 scores are unbounded and corpus-dependent while cosine sits in 0..1,
    so any score-based blend would need a normalisation that shifts every time
    the corpus changes.
    """
    fused: dict[int, float] = {}
    for ids in rankings.values():
        for rank, idx in enumerate(ids, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + rank)
    return fused


class CrossEncoderReranker:
    """
    Lazily-loaded cross-encoder. The model is ~90MB and downloads on first use,
    so it is not touched during startup - a Week 3 user never pays for it.
    """

    def __init__(self, model_name: str = RERANK_MODEL_NAME) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._failed = False

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def unavailable(self) -> bool:
        return self._failed

    def _load(self) -> Any:
        if self._model is not None or self._failed:
            return self._model
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
            logger.info("Loaded reranker %s", self.model_name)
        except Exception as exc:  # network, disk, or torch problem
            self._failed = True
            logger.warning("Reranker %s unavailable (%s); keeping fused order", self.model_name, exc)
        return self._model

    def score(self, query: str, texts: Sequence[str]) -> Optional[list[float]]:
        """Return one relevance logit per text, or None if reranking is off."""
        if not texts:
            return None
        model = self._load()
        if model is None:
            return None
        try:
            raw = model.predict([(query, text) for text in texts])
        except Exception as exc:  # pragma: no cover - runtime inference failure
            logger.warning("Reranking failed (%s); keeping fused order", exc)
            return None
        return [float(value) for value in raw]


_reranker: CrossEncoderReranker | None = None


def get_reranker() -> CrossEncoderReranker:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoderReranker()
    return _reranker


@dataclass
class Scored:
    """
    One retrieved chunk with every stage's score kept separately.

    They are deliberately not collapsed into a single number: the UI shows the
    dense cosine (comparable to SCORE_THRESHOLD), the BM25 contribution, and
    the rerank logit side by side so a reviewer can see *which* stage promoted
    a chunk.
    """

    index: int
    dense_score: float = 0.0
    keyword_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: Optional[float] = None
    dense_rank: Optional[int] = None
    keyword_rank: Optional[int] = None

    @property
    def retriever(self) -> str:
        if self.dense_rank is not None and self.keyword_rank is not None:
            return "both"
        if self.keyword_rank is not None:
            return "keyword"
        return "dense"


def availability() -> dict:
    reranker = get_reranker()
    return {
        "hybrid_available": BM25_AVAILABLE,
        "reranker_available": not reranker.unavailable,
        "reranker_loaded": reranker.loaded,
        "reranker_model": RERANK_MODEL_NAME,
    }


def mmr_select(
    order: Sequence[int],
    relevance: dict[int, float],
    similarity: "Any",
    top_k: int,
    lam: float,
) -> list[int]:
    """
    Maximal Marginal Relevance over an already-ranked candidate list.

    MMR repeatedly picks the candidate maximising

        lam * relevance - (1 - lam) * max similarity to anything already picked

    so a chunk that merely repeats what is already selected is passed over. On
    this corpus that is a real condition rather than a hypothetical: KB-007
    holds six plan packs that differ from the retail ones mainly in a numeric
    identifier, so an error-code or plan query can fill its whole top-3 with
    near-copies of one section.

    `relevance` must already be min-max normalised into 0..1. The raw ordering
    scores are not usable here: an RRF score sits around 0.016-0.03 and a
    cross-encoder logit runs -11..+11, while `similarity` is a cosine in 0..1.
    Subtracting one from the other unnormalised would make `lam` mean a
    different thing in every arm. Normalising per query keeps `lam` comparable
    and is why a single tuned value can be reported.

    `similarity(a, b)` returns the cosine between two candidate chunks.
    lam = 1.0 reproduces the input order exactly, which is what makes MMR
    switchable off by value rather than by branch.
    """
    remaining = list(order)
    selected: list[int] = []
    while remaining and len(selected) < top_k:
        best_idx = None
        best_score = None
        for idx in remaining:
            penalty = max((similarity(idx, chosen) for chosen in selected), default=0.0)
            score = lam * relevance.get(idx, 0.0) - (1.0 - lam) * penalty
            if best_score is None or score > best_score:
                best_score = score
                best_idx = idx
        selected.append(best_idx)
        remaining.remove(best_idx)
    return selected


def minmax(values: dict[int, float]) -> dict[int, float]:
    """Scale a score map into 0..1. A flat map becomes all-1.0, not a divide by zero."""
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi - lo < 1e-12:
        return {k: 1.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}
