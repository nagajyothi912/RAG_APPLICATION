"""
Follow-up questions: history trimming, the standalone-question rewrite, the
suggestion chips, and the history the MCP agent receives.

No test calls Groq. The RAG tests stub `service.client` with a scripted fake,
and the agent test uses the echo fixture server and a fake async client.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents.week9 import agent as week9_agent
from app.main import app
from app.services import follow_up
from app.services import rag_service as rag_module
from app.services.rag_service import get_rag_service

SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample_documents"
PLANS = SAMPLE_ROOT / "help_centre" / "airfiber_plans.md"
ECHO_SERVER = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"

HISTORY = [
    {"role": "user", "content": "What does AirFiber_1199_1M include?"},
    {"role": "assistant", "content": "AirFiber_1199_1M is 200 Mbps unlimited data."},
]
REWRITTEN = "What is the price of the AirFiber_1999_3M plan?"


def _response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class ScriptedCompletions:
    """Returns the scripted replies in order, then repeats the last one."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return _response(reply)


def _client(completions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


# ---- trim_history -----------------------------------------------------------


def test_trim_history_keeps_the_last_turns_and_drops_junk():
    turns = [{"role": "user", "content": f"q{i}"} for i in range(10)]
    turns += [{"role": "system", "content": "ignore me"}, {"role": "assistant", "content": "   "}]
    trimmed = follow_up.trim_history(turns)
    assert [t["content"] for t in trimmed] == [f"q{i}" for i in range(4, 10)]
    assert len(trimmed) == follow_up.MAX_HISTORY_MESSAGES


def test_trim_history_truncates_long_messages_and_accepts_models():
    long = SimpleNamespace(role="assistant", content="x" * 5000)
    (turn,) = follow_up.trim_history([long])
    assert len(turn["content"]) == follow_up.MAX_HISTORY_CHARS + 1
    assert follow_up.trim_history(None) == []


# ---- rewrite_question -------------------------------------------------------


def test_rewrite_without_history_makes_no_call():
    completions = ScriptedCompletions("unused")
    question, info = follow_up.rewrite_question(_client(completions), "m", "hi", [])
    assert question == "hi" and not info["rewritten"]
    assert completions.calls == []


def test_rewrite_returns_the_standalone_question_and_sends_the_history():
    completions = ScriptedCompletions(f'Standalone question: "{REWRITTEN}"\nextra line')
    question, info = follow_up.rewrite_question(
        _client(completions), "m", "and the 3M one?", HISTORY, temperature=None
    )
    assert question == REWRITTEN
    assert info["rewritten"] and info["original_question"] == "and the 3M one?"
    sent = completions.calls[0]
    assert "temperature" not in sent  # unset temperature sends none, as everywhere else
    assert "AirFiber_1199_1M is 200 Mbps" in sent["messages"][1]["content"]


@pytest.mark.parametrize("reply", [RuntimeError("groq down"), "", "y" * 1000])
def test_a_failed_or_unusable_rewrite_falls_back_to_the_typed_question(reply):
    question, info = follow_up.rewrite_question(
        _client(ScriptedCompletions(reply)), "m", "and the 3M one?", HISTORY
    )
    assert question == "and the 3M one?"
    assert not info["rewritten"] and info["error"]


# ---- suggest_follow_ups -----------------------------------------------------


def _chunk(article_id, section):
    return SimpleNamespace(article_id=article_id, section=section)


def test_suggestions_skip_what_was_answered_and_offer_the_rest_of_the_cited_articles():
    chunks = [
        _chunk("KB-001", "Plans"),  # bare title: never offered
        _chunk("KB-001", "Plans > A plan"),
        _chunk("KB-001", "Plans > A plan"),  # second chunk of a section: offered once
        _chunk("KB-001", "Plans > B plan"),
        _chunk("KB-001", "Plans > Comparison"),
        _chunk("KB-002", "Billing > Refunds"),
        _chunk("KB-009", "Other > Not cited"),
    ]
    cited = [("KB-001", "Plans > A plan"), ("KB-002", "Billing > Late fees"), ("KB-001", "Plans > B plan")]
    out = follow_up.suggest_follow_ups(chunks, cited)
    # B plan was cited, but only at rank 3: still worth offering
    assert [s["label"] for s in out] == ["B plan", "Comparison", "Refunds"]
    assert out[0]["question"] == "Tell me about B plan (Plans)"
    assert follow_up.suggest_follow_ups(chunks, [("KB-001", "Plans > A plan")], limit=1) == out[:1]
    assert follow_up.suggest_follow_ups(chunks, []) == []


# ---- /api/chat --------------------------------------------------------------


@pytest.fixture
def chat(monkeypatch):
    with TestClient(app) as client:
        client.post(
            "/api/documents/upload", files=[("files", (PLANS.name, PLANS.read_bytes(), "text/markdown"))]
        )
        service = get_rag_service()
        previous = service.client
        monkeypatch.setattr(rag_module.settings, "groq_api_key", "test-key")

        def install(*replies):
            completions = ScriptedCompletions(*replies)
            service.client = _client(completions)
            return completions

        yield client, install
        service.client = previous


def test_chat_without_history_is_unchanged(chat):
    client, install = chat
    completions = install("200 Mbps unlimited (source: airfiber_plans.md).")
    body = client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"}).json()
    assert len(completions.calls) == 1  # no rewrite call
    assert body["rewritten_question"] == ""
    assert body["follow_ups"], "an answered question offers other sections of the article"
    assert all(s["label"] for s in body["follow_ups"])


def test_a_follow_up_is_rewritten_before_retrieval_and_traced(chat, traces):
    client, install = chat
    completions = install(REWRITTEN, "It costs 1999 (source: airfiber_plans.md).")
    response = client.post(
        "/api/chat", json={"message": "and the 3M one?", "mode": "week4", "history": HISTORY}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rewritten_question"] == REWRITTEN
    assert len(completions.calls) == 2
    # the answer prompt asks the standalone question, not the fragment
    assert REWRITTEN in completions.calls[1]["messages"][1]["content"]
    assert any("1999_3M" in s["section"] for s in body["sources"])

    (record,) = traces()
    assert record["request"]["question"] == REWRITTEN
    assert record["request"]["follow_up"]["original_question"] == "and the 3M one?"
    assert record["request"]["follow_up"]["history_messages"] == 2


def test_a_chat_without_history_writes_no_follow_up_block(chat, traces):
    client, install = chat
    install("200 Mbps unlimited (source: airfiber_plans.md).")
    client.post("/api/chat", json={"message": "What does AirFiber_1199_1M include?"})
    assert "follow_up" not in traces()[0]["request"]


# ---- Week 9 agent -----------------------------------------------------------


class _AsyncCompletions:
    def __init__(self):
        self.requests = []

    async def create(self, **request):
        self.requests.append(json.loads(json.dumps(request, default=str)))
        message = SimpleNamespace(content="Final reply.", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def test_the_agent_sees_history_before_the_question(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps({"mcpServers": {"one": {"command": "${PYTHON}", "args": [str(ECHO_SERVER), "one"]}}}), "utf-8"
    )
    completions = _AsyncCompletions()
    trace = asyncio.run(
        week9_agent.run(
            "and the 3M one?", config_path=config, model="m",
            client=SimpleNamespace(chat=SimpleNamespace(completions=completions)), history=HISTORY,
        )
    )
    messages = completions.requests[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1:3] == HISTORY
    assert messages[-1]["content"] == "and the 3M one?"
    assert trace["history_messages"] == 2
