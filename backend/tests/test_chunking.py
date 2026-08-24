from pathlib import Path

SAMPLE = Path(__file__).resolve().parents[2] / "sample_documents" / "help_centre" / "airfiber_plans.md"


def test_notebook_chunking_matches_service():
    from app.services.rag_service import chunk_text

    text = SAMPLE.read_text(encoding="utf-8")
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert chunks
    assert all(len(chunk) <= 500 for chunk in chunks)
    if len(chunks) > 1:
        assert chunks[0][-50:] == chunks[1][:50]
