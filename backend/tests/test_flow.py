from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import rag_service as rag_module
from app.services.rag_service import answer_with_groq, get_rag_service

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_documents"


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _file_tuple(path: Path, upload_name: str | None = None):
    return (upload_name or path.name, path.read_bytes(), "application/octet-stream")


def test_health(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["embedder_ready"] is True


def test_upload_single_document(client: TestClient):
    path = SAMPLE_ROOT / "help_centre" / "airfiber_plans.md"
    response = client.post(
        "/api/documents/upload",
        files=[("files", (path.name, path.read_bytes(), "text/markdown"))],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert path.name in body["uploaded"]
    assert body["indexed_chunks"] > 0
    assert path.name in body["documents"]


def test_upload_multiple_documents(client: TestClient):
    files = [
        ("files", _file_tuple(SAMPLE_ROOT / "help_centre" / "billing_faq.md")),
        ("files", _file_tuple(SAMPLE_ROOT / "policies" / "refund_policy.txt")),
    ]
    response = client.post("/api/documents/upload", files=files)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["uploaded"]) >= {"billing_faq.md", "refund_policy.txt"}
    assert body["indexed_chunks"] > 0


def test_upload_folder_paths(client: TestClient):
    files = [
        (
            "files",
            _file_tuple(
                SAMPLE_ROOT / "help_centre" / "airfiber_plans.md",
                "help_centre/airfiber_plans.md",
            ),
        ),
        (
            "files",
            _file_tuple(
                SAMPLE_ROOT / "help_centre" / "billing_faq.md",
                "help_centre/billing_faq.md",
            ),
        ),
    ]
    response = client.post("/api/documents/upload", files=files)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "help_centre/airfiber_plans.md" in body["documents"]
    assert "help_centre/billing_faq.md" in body["documents"]


def test_invalid_file_rejected(client: TestClient):
    path = SAMPLE_ROOT / "not_supported.bin"
    response = client.post(
        "/api/documents/upload",
        files=[("files", (path.name, path.read_bytes(), "application/octet-stream"))],
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "skipped" in detail
    assert detail["skipped"][0]["filename"] == "not_supported.bin"


def test_mixed_valid_and_invalid(client: TestClient):
    files = [
        ("files", _file_tuple(SAMPLE_ROOT / "policies" / "refund_policy.txt")),
        ("files", _file_tuple(SAMPLE_ROOT / "not_supported.bin")),
    ]
    response = client.post("/api/documents/upload", files=files)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "refund_policy.txt" in body["uploaded"]
    assert body["skipped"][0]["filename"] == "not_supported.bin"


def test_upload_pdf(client: TestClient):
    pdf_path = Path(__file__).resolve().parents[2] / "Week3_Module2_Retrieval_and_RAG.pdf"
    response = client.post(
        "/api/documents/upload",
        files=[("files", (pdf_path.name, pdf_path.read_bytes(), "application/pdf"))],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert pdf_path.name in body["uploaded"]
    assert body["indexed_chunks"] > 0


def test_list_documents(client: TestClient):
    path = SAMPLE_ROOT / "policies" / "refund_policy.txt"
    client.post("/api/documents/upload", files=[("files", _file_tuple(path))])
    response = client.get("/api/documents")
    assert response.status_code == 200
    body = response.json()
    assert "refund_policy.txt" in body["documents"]
    assert body["indexed_chunks"] >= 1


def test_delete_document(client: TestClient):
    path = SAMPLE_ROOT / "policies" / "refund_policy.txt"
    client.post("/api/documents/upload", files=[("files", _file_tuple(path))])
    response = client.delete("/api/documents", params={"name": path.name})
    assert response.status_code == 200, response.text
    body = response.json()
    assert path.name not in body["documents"]


def test_delete_missing_document(client: TestClient):
    response = client.delete("/api/documents", params={"name": "does-not-exist.md"})
    assert response.status_code == 404


def test_unknown_question_short_circuits_without_llm():
    from app.services.rag_service import Chunk, SCORE_THRESHOLD

    empty = answer_with_groq(None, "unused-model", "What is the capital of mongolia ?", [])
    assert empty == "I don't know. That isn't covered in the documents I have."

    weak_hit = [
        (Chunk(text="unrelated filler text", source="notes.md", chunk_id=0), SCORE_THRESHOLD - 0.01)
    ]
    weak = answer_with_groq(None, "unused-model", "What is the capital of mongolia ?", weak_hit)
    assert weak == "I don't know. That isn't covered in the documents I have."


def test_retrieval_finds_airfiber_plan(client: TestClient):
    path = SAMPLE_ROOT / "help_centre" / "airfiber_plans.md"
    client.post("/api/documents/upload", files=[("files", _file_tuple(path))])
    service = get_rag_service()
    results = service.store.search("What are the benefits of AirFiber_1199_1M plan", top_k=3)
    assert results
    chunk, score = results[0]
    assert "airfiber_plans" in chunk.source.lower()
    assert score > 0.08
    assert "1199" in chunk.text or "200 Mbps" in chunk.text


def test_chat_without_api_key(client: TestClient, monkeypatch):
    monkeypatch.setattr(rag_module.settings, "groq_api_key", "")
    path = SAMPLE_ROOT / "help_centre" / "airfiber_plans.md"
    client.post("/api/documents/upload", files=[("files", _file_tuple(path))])
    service = get_rag_service()
    previous_client = service.client
    service.client = None
    try:
        response = client.post("/api/chat", json={"message": "What are the benefits of AirFiber_1199_1M plan"})
        assert response.status_code == 502
        assert "GROQ_API_KEY" in response.json()["detail"]
    finally:
        service.client = previous_client


def test_chat_empty_message(client: TestClient):
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code in (400, 422)


def test_chat_known_and_unknown_with_stubbed_llm(client: TestClient, monkeypatch):
    path = SAMPLE_ROOT / "help_centre" / "airfiber_plans.md"
    client.post("/api/documents/upload", files=[("files", _file_tuple(path))])

    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def create(self, **kwargs):
            user_prompt = kwargs["messages"][-1]["content"]
            if "mongolia" in user_prompt.lower():
                return FakeResponse("I don't know based on the provided documents.")
            return FakeResponse(
                "The AirFiber_1199_1M plan includes 200 Mbps unlimited speed (source: airfiber_plans.md)."
            )

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    service = get_rag_service()
    previous_client = service.client
    service.client = FakeClient()
    monkeypatch.setattr(rag_module.settings, "groq_api_key", "test-key")

    try:
        known = client.post(
            "/api/chat",
            json={"message": "What are the benefits of AirFiber_1199_1M plan"},
        )
        assert known.status_code == 200, known.text
        body = known.json()
        assert "200 Mbps" in body["answer"]
        assert body["sources"]
        assert "airfiber_plans" in body["sources"][0]["source"]

        unknown = client.post("/api/chat", json={"message": "What is the capital of mongolia ?"})
        assert unknown.status_code == 200, unknown.text
        assert "don't know" in unknown.json()["answer"].lower()
    finally:
        service.client = previous_client
