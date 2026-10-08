"""
Role-based login: who can reach what.

conftest.py turns AUTH_ENABLED off for the rest of the suite; every test here
turns it back on, so these are the only tests that see the real gatekeeping.
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import auth


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    with TestClient(app) as test_client:
        yield test_client


def _token(client, username, password, role=None):
    body = {"username": username, "password": password}
    if role:
        body["role"] = role
    response = client.post("/api/auth/login", json=body)
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_role(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    assert response.json()["user"] == {"username": "admin", "role": "admin"}

    response = client.post("/api/auth/login", json={"username": "user", "password": "user123"})
    assert response.json()["user"]["role"] == "chatbot"


@pytest.mark.parametrize(
    "username,password",
    [("admin", "wrong"), ("nobody", "admin123"), ("admin", "pässwörd")],
)
def test_bad_credentials_are_rejected(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 401


def test_role_on_login_screen_must_match_account(client):
    response = client.post(
        "/api/auth/login", json={"username": "user", "password": "user123", "role": "admin"}
    )
    assert response.status_code == 403
    _token(client, "admin", "admin123", role="admin")


def test_me_echoes_the_token_owner(client):
    token = _token(client, "user", "user123")
    assert client.get("/api/auth/me", headers=_auth(token)).json() == {
        "username": "user",
        "role": "chatbot",
    }


def test_health_is_public_but_the_rest_needs_a_token(client):
    assert client.get("/api/health").status_code == 200
    for path in ("/api/documents", "/api/golden-questions", "/api/auth/me", "/api/week6/results"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401


def test_chatbot_can_read_but_not_administer(client):
    headers = _auth(_token(client, "user", "user123"))
    assert client.get("/api/documents", headers=headers).status_code == 200
    assert client.get("/api/golden-questions", headers=headers).status_code == 200

    admin_only = [
        ("get", "/api/analysis/summary"),
        ("get", "/api/week6/results"),
        ("get", "/api/week7/report"),
        ("get", "/api/week8/results"),
        ("delete", "/api/documents?name=anything.md"),
    ]
    for method, path in admin_only:
        assert getattr(client, method)(path, headers=headers).status_code == 403, path

    upload = client.post(
        "/api/documents/upload",
        headers=headers,
        files=[("files", ("note.md", b"# Note\nhello", "text/markdown"))],
    )
    assert upload.status_code == 403


def test_admin_reaches_admin_routes(client):
    headers = _auth(_token(client, "admin", "admin123"))
    assert client.get("/api/analysis/summary", headers=headers).status_code == 200
    assert client.get("/api/week8/results", headers=headers).status_code == 200


def test_week6_results_match_the_committed_runs(client):
    headers = _auth(_token(client, "admin", "admin123"))
    data = client.get("/api/week6/results", headers=headers).json()
    assert data["available"]
    assert data["few_shot_tickets"] == ["T017", "T022"]
    by_label = {run["label"]: run for run in data["runs"]}
    # The headline numbers in docs/week6/README.md: 24/26 before, 25/26 after.
    assert (by_label["v1 · single run"]["agree"], by_label["v1 · single run"]["total"]) == (24, 26)
    assert (by_label["v2 · majority of 3"]["agree"], by_label["v2 · majority of 3"]["total"]) == (25, 26)
    assert by_label["v2 · majority of 3"]["held_out_total"] == 24


def test_tampered_or_expired_tokens_are_rejected(client, monkeypatch):
    token = _token(client, "user", "user123")
    payload, signature = token.split(".")
    forged = auth._b64(b'{"sub":"user","role":"admin","exp":9999999999}') + "." + signature
    assert client.get("/api/auth/me", headers=_auth(forged)).status_code == 401
    assert client.get("/api/auth/me", headers=_auth("not-a-token")).status_code == 401

    monkeypatch.setattr(time, "time", lambda: 10**12)
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401
