import json
import os
import tempfile
import zlib
from pathlib import Path

import pytest

# DOCS_DIR must be redirected before app.config is imported anywhere, otherwise
# the test run writes into the real backend/data/docs.
TMP_DOCS = tempfile.mkdtemp(prefix="rag-docs-")
os.environ["DOCS_DIR"] = TMP_DOCS
os.environ.setdefault("GROQ_API_KEY", "")

# Pin the retrieval configuration chosen in results.md. backend/.env is
# developer-local and gitignored, so without this the suite would pass or fail
# depending on whose machine it runs on. Env vars outrank the .env file in
# pydantic-settings, so these win.
os.environ["CHUNK_STRATEGY"] = "heading"
os.environ["CHUNK_SIZE"] = "1000"
os.environ["CHUNK_OVERLAP"] = "100"
os.environ["TOP_K"] = "5"
os.environ["SCORE_THRESHOLD"] = "0.15"

# Tracing must be off for the suite, and pointed somewhere harmless if a test
# turns it on. Same reason DOCS_DIR is redirected above: a developer with
# TRACE_ENABLED=true in backend/.env must not be able to make the test run
# append to the real trace file.
os.environ["TRACE_ENABLED"] = "false"
os.environ["TRACE_PATH"] = str(Path(TMP_DOCS).parent / "rag-traces" / "test.jsonl")


def _pdf_bytes(text: str) -> bytes:
    """
    Build a minimal single-page PDF containing `text`.

    The suite used to read a PDF from the repo root that was never committed, so
    the PDF upload path failed on a clean clone. Generating the fixture keeps
    that path covered without adding a PDF-writer dependency.
    """
    content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
    stream = zlib.compress(content)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" /Filter /FlateDecode >>\nstream\n"
        + stream
        + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n".encode()
        + b"%%EOF\n"
    )
    return bytes(out)


@pytest.fixture(scope="session")
def sample_pdf() -> bytes:
    return _pdf_bytes("AirFiber quarterly retrieval report")


@pytest.fixture
def traces(tmp_path, monkeypatch):
    """
    Tracing on, into a temp file, for the life of one test.

    Monkeypatches the module-level writer rather than `settings`, which is how
    this suite already handles `service.client`: it is explicit, monkeypatch
    reverses it automatically, and it does not depend on settings-reload
    semantics. Yields a reader returning the parsed records written so far.
    """
    from app.services import tracing

    path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "_writer", tracing.TraceWriter(path=path, enabled=True))

    def read():
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]

    read.path = path
    yield read
    monkeypatch.setattr(tracing, "_writer", None)
