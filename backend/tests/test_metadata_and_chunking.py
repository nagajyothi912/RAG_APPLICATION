"""Covers the metadata contract, the chunking strategies, and metadata filtering."""

from pathlib import Path

import pytest

from app.services.chunking import chunk_by_heading, chunk_document, chunk_fixed_text, chunk_recursive
from app.services.rag_service import (
    METADATA_FIELDS,
    UNCATEGORIZED,
    build_chunks,
    derive_metadata,
    format_citation,
    load_documents,
    parse_front_matter,
)

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_documents"
TROUBLESHOOTING = SAMPLE_ROOT / "help_centre" / "troubleshooting_connectivity.md"


# --- front matter and metadata -------------------------------------------------


def test_front_matter_is_parsed_and_stripped():
    meta, body = parse_front_matter(
        "---\narticle_id: KB-999\nproduct_area: billing\nlast_updated: 2026-01-01\n---\n\n# Title\nBody"
    )
    assert meta["article_id"] == "KB-999"
    assert meta["product_area"] == "billing"
    assert body.startswith("# Title")
    assert "article_id" not in body


def test_document_without_front_matter_still_gets_metadata():
    meta = derive_metadata("help_centre/manual.pdf", {})
    assert meta["source_file"] == "help_centre/manual.pdf"
    assert meta["article_id"] == "manual"
    assert meta["product_area"] == "help_centre"  # falls back to the folder
    assert meta["last_updated"] == "unknown"


def test_flat_file_without_front_matter_is_uncategorized():
    assert derive_metadata("notes.txt", {})["product_area"] == UNCATEGORIZED


def test_every_corpus_chunk_carries_the_four_required_fields():
    chunks = build_chunks(str(SAMPLE_ROOT), chunk_size=1000, overlap=100, strategy="heading")
    assert chunks
    for chunk in chunks:
        meta = chunk.metadata()
        assert set(meta) == set(METADATA_FIELDS)
        assert meta["article_id"].startswith("KB-")
        assert meta["product_area"] != UNCATEGORIZED
        assert meta["last_updated"] != "unknown"


def test_corpus_articles_all_carry_a_unique_id():
    """
    KB-007 (`airfiber_legacy_plans.md`) was added to give the Week 4 comparison a
    query the dense retriever actually fails: a corpus of near-duplicate plan
    names is the condition under which an exact identifier is the only signal
    that separates the right chunk from six wrong ones. What matters here is not
    the count but that no two articles claim the same id - a duplicate would make
    `article_id` useless for citation and filtering.
    """
    docs = load_documents(str(SAMPLE_ROOT))
    ids = [d.metadata["article_id"] for d in docs]
    assert len(docs) == 7
    assert len(set(ids)) == len(ids)


# --- chunking strategies -------------------------------------------------------


def test_fixed_strategy_matches_the_notebook_splitter():
    text = TROUBLESHOOTING.read_text(encoding="utf-8")
    pieces = chunk_document(text, strategy="fixed", chunk_size=500, overlap=50)
    assert [p.text for p in pieces] == chunk_fixed_text(text, 500, 50)


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError, match="Unknown chunking strategy"):
        chunk_document("text", strategy="semantic")


@pytest.mark.parametrize("strategy", ["fixed", "recursive", "heading"])
def test_every_strategy_produces_non_empty_chunks(strategy):
    chunks = build_chunks(str(SAMPLE_ROOT), chunk_size=1000, overlap=100, strategy=strategy)
    assert chunks
    assert all(chunk.text.strip() for chunk in chunks)


def test_heading_strategy_prefixes_the_section_path():
    text = TROUBLESHOOTING.read_text(encoding="utf-8")
    pieces = chunk_by_heading(text, chunk_size=1000, overlap=100)
    error_pieces = [p for p in pieces if "AF-503" in p.text]
    assert error_pieces
    assert all("Error codes" in p.section for p in error_pieces)
    assert all(p.text.startswith(p.section) for p in error_pieces)


def test_heading_strategy_keeps_a_table_intact_when_it_fits():
    """The LED table is ~740 chars; at 1000 it must stay whole, header row included."""
    text = TROUBLESHOOTING.read_text(encoding="utf-8")
    pieces = chunk_by_heading(text, chunk_size=1000, overlap=100)
    holders = [p for p in pieces if "Fiber cut detected" in p.text]
    assert len(holders) == 1
    piece = holders[0]
    assert "| LED colour | Pattern | Meaning | What to do |" in piece.text
    assert "Solid | No optical signal" in piece.text


def test_fixed_strategy_splits_that_same_table():
    """Documents the failure mode measured in results.md: the notebook splitter cuts tables."""
    text = TROUBLESHOOTING.read_text(encoding="utf-8")
    pieces = chunk_fixed_text(text, 500, 50)
    holders = [p for p in pieces if "Fiber cut detected" in p]
    assert holders
    assert all("| LED colour | Pattern | Meaning | What to do |" not in p for p in holders)


def test_recursive_strategy_respects_the_size_target():
    text = TROUBLESHOOTING.read_text(encoding="utf-8")
    overlap = 80
    pieces = chunk_recursive(text, chunk_size=800, overlap=overlap)
    assert pieces
    assert all(len(p.text) <= 800 + overlap for p in pieces)


# --- citations -----------------------------------------------------------------


def test_citation_names_source_article_and_section():
    chunks = build_chunks(str(SAMPLE_ROOT), chunk_size=1000, overlap=100, strategy="heading")
    chunk = next(c for c in chunks if "AF-503" in c.text)
    citation = format_citation(chunk)
    assert "troubleshooting_connectivity.md" in citation
    assert "KB-004" in citation
    assert "Error codes" in citation
    assert f"chunk #{chunk.chunk_id}" in citation
