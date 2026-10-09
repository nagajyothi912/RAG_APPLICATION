"""
Week 9: the MCP host, the discovering agent and the help-centre server.

No test here calls Groq: the agent loop runs against a scripted fake client,
and the host tests use a tiny fixture server instead of the real ones.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.week9 import agent as week9_agent
from app.agents.week9.mcp_host import McpHost, load_config

BACKEND = Path(__file__).resolve().parents[1]
AGENT_DIR = BACKEND / "app" / "agents" / "week9"
ECHO_SERVER = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"


def _config(tmp_path, servers: dict) -> Path:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}), "utf-8")
    return path


def _echo(name="echo"):
    return {"command": "${PYTHON}", "args": [str(ECHO_SERVER), name]}


def test_agent_module_names_no_server_or_tool():
    """The zero-diff requirement only holds if the agent never hard-codes what it connects to."""
    forbidden = [
        "search_help_centre", "get_article", "lookup_ticket", "get_escalation_history",
        "help-centre", "help_centre", "ticket-history", "ticket_history", "TCK-",
    ]
    for path in AGENT_DIR.glob("*.py"):
        source = path.read_text("utf-8")
        for name in forbidden:
            assert name not in source, f"{path.name} mentions {name!r}"


def test_load_config_resolves_python_and_cwd(tmp_path):
    path = _config(tmp_path, {"a": {"command": "${PYTHON}", "args": ["-m", "x"], "cwd": "sub"}, "b": {"url": "http://h/mcp", "disabled": True}})
    (server,) = load_config(path)
    assert server.command == sys.executable
    assert server.cwd == str((tmp_path / "sub").resolve())


def test_host_discovers_routes_and_namespaces(tmp_path):
    async def go():
        async with McpHost(_config(tmp_path, {"one": _echo("one"), "two": _echo("two")})) as host:
            discovery = host.discovery()
            assert discovery["tool_count"] == 6
            assert discovery["servers"]["one"]["tools"] == ["echo", "whoami", "fail"]
            # the second server's identical names are namespaced, not dropped
            assert set(host.tools) == {"echo", "whoami", "fail", "two__echo", "two__whoami", "two__fail"}
            assert [t["function"]["name"] for t in host.openai_tools()] == list(host.tools)

            ok = await host.call("two__echo", {"text": "hi"})
            assert (ok.server, ok.tool, ok.is_error, ok.text) == ("two", "echo", False, "hi")
            bad = await host.call("fail", {"reason": "nope"})
            assert bad.is_error and "failed: nope" in bad.text
            missing = await host.call("no_such_tool", {})
            assert missing.is_error and "Available tools" in missing.text

    asyncio.run(go())


class _FakeCompletions:
    """Replays scripted model turns and records what the agent sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []

    async def create(self, **request):
        self.requests.append(json.loads(json.dumps(request, default=str)))
        content, calls = self.turns.pop(0)
        tool_calls = [
            SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
            for i, (name, args) in enumerate(calls)
        ]
        message = SimpleNamespace(content=content, tool_calls=tool_calls or None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def test_agent_loop_uses_discovered_tools(tmp_path):
    completions = _FakeCompletions([("", [("echo", {"text": "pong"})]), ("Final reply.", [])])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    trace = asyncio.run(
        week9_agent.run("ping?", config_path=_config(tmp_path, {"one": _echo()}), model="m", client=client)
    )
    assert trace["final_reply"] == "Final reply."
    assert trace["tools_called"] == ["one.echo"]
    assert [t["function"]["name"] for t in completions.requests[0]["tools"]] == ["echo", "whoami", "fail"]
    # the tool result went back to the model on the next turn
    assert completions.requests[1]["messages"][-1] == {"role": "tool", "tool_call_id": "c0", "content": "pong"}


def test_seed_call_runs_before_the_model(tmp_path):
    completions = _FakeCompletions([("Could not do it.", [])])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    trace = asyncio.run(
        week9_agent.run(
            "q", config_path=_config(tmp_path, {"one": _echo()}), model="m", client=client,
            seed_call=("fail", {"reason": "seeded"}),
        )
    )
    seeded = trace["steps"][0]
    assert seeded["seeded"] and seeded["is_error"] and "seeded" in seeded["text"]
    assert completions.requests[0]["messages"][-1]["role"] == "tool"


def test_help_centre_server_tools_in_memory():
    from mcp.shared.memory import create_connected_server_and_client_session

    from mcp_servers.help_centre import server

    async def go():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as session:
            names = [tool.name for tool in (await session.list_tools()).tools]
            assert names == ["search_help_centre", "get_article"]
            missing = await session.call_tool("get_article", {"article_id": "KB-999"})
            assert missing.isError

    asyncio.run(go())


def test_get_article_error_is_recoverable():
    """Requirement 5: the not-found message says the format, suggests the fix and lists valid ids."""
    from mcp_servers.help_centre.server import _not_found_message

    message = _not_found_message("KB-4", {"KB-004": "Troubleshooting", "KB-001": "Plans"})
    assert "KB-nnn" in message and "Did you mean KB-004?" in message
    assert "KB-001 (Plans); KB-004 (Troubleshooting)" in message
    assert "Error 3" not in message
    assert "Did you mean" not in _not_found_message("KB-999", {"KB-004": "Troubleshooting"})


def test_ticket_history_server_in_memory(tmp_path, monkeypatch):
    from mcp.shared.memory import create_connected_server_and_client_session

    from mcp_servers.ticket_history import server

    monkeypatch.setattr(server, "ACCESS_LOG", tmp_path / "access.log")

    async def go():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as session:
            names = [tool.name for tool in (await session.list_tools()).tools]
            assert names == ["list_tickets", "lookup_ticket", "get_escalation_history"]

            listed = json.loads((await session.call_tool("list_tickets", {})).content[0].text)["tickets"]
            assert len(listed) == 5 and listed[0]["last_update"] >= listed[-1]["last_update"]

            found = await session.call_tool("lookup_ticket", {"ticket_id": "tck-4471"})
            assert not found.isError and "Priya Raman" in found.content[0].text

            history = await session.call_tool("get_escalation_history", {"ticket_id": "TCK-4471"})
            assert json.loads(history.content[0].text)["escalations"][0]["team"] == "Field Dispatch"

            malformed = await session.call_tool("lookup_ticket", {"ticket_id": "4471"})
            assert malformed.isError and "TCK-nnnn" in malformed.content[0].text
            missing = await session.call_tool("lookup_ticket", {"ticket_id": "TCK-9999"})
            assert missing.isError and "not found" in missing.content[0].text

            # the host's caller travels as _meta and lands in the access log
            await session.call_tool(
                "lookup_ticket", {"ticket_id": "TCK-4410"}, meta={"caller": {"username": "user", "role": "chatbot"}}
            )

    asyncio.run(go())
    lines = (tmp_path / "access.log").read_text().splitlines()
    assert len(lines) == 6
    assert "caller=unscoped tool=list_tickets ticket_id=* outcome=5_listed" in lines[0]
    assert "caller=unscoped tool=lookup_ticket ticket_id=TCK-4471 outcome=found" in lines[1]
    assert "caller=user/chatbot tool=lookup_ticket ticket_id=TCK-4410 outcome=found" in lines[-1]


def test_in_process_transport_forwards_caller_meta(tmp_path):
    """The web app runs a server inside its own process; it is still a real MCP session."""
    config = _config(tmp_path, {"local": {"module": "tests.fixtures.mcp_echo_server", "object": "mcp"}})

    async def go():
        async with McpHost(config) as host:
            assert host.discovery()["servers"]["local"]["transport"] == "in-process"
            assert (await host.call("echo", {"text": "hi"})).text == "hi"
            who = await host.call("whoami", {}, meta={"caller": {"username": "user", "role": "chatbot"}})
            assert "'username': 'user'" in who.text
            assert (await host.call("whoami", {})).text == "nobody"

    asyncio.run(go())


def test_agent_always_replies_when_out_of_turns(tmp_path):
    """Out of tool turns, the agent makes one last call with tools off instead of returning nothing."""
    completions = _FakeCompletions(
        [("", [("echo", {"text": "a"})]), ("", [("echo", {"text": "b"})]), ("Best effort reply.", [])]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    trace = asyncio.run(
        week9_agent.run("q", config_path=_config(tmp_path, {"one": _echo()}), model="m", client=client, max_iterations=2)
    )
    assert trace["final_reply"] == "Best effort reply."
    assert trace["stop_reason"] == "max_iterations (2), answered without tools"
    assert completions.requests[-1]["tool_choice"] == "none"


def test_assistant_response_extracts_sources_and_tickets():
    from app.services.assistant import _response

    passage = {"article_id": "KB-004", "source_file": "t.md", "section": "LEDs", "product_area": "troubleshooting", "text": "red"}
    trace = {
        "final_reply": "Answer.",
        "stop_reason": "answered",
        "steps": [
            {"type": "model", "usage": {"total_tokens": 10}},
            {"type": "tool_call", "server": "h", "tool": "search", "arguments": {"query": "x"}, "is_error": False,
             "latency_ms": 5.0, "text": json.dumps({"passages": [passage, passage]})},
            {"type": "tool_call", "server": "t", "tool": "lookup", "arguments": {"ticket_id": "TCK-4410"},
             "is_error": False, "latency_ms": 2.0, "text": json.dumps({"ticket_id": "TCK-4410"})},
            {"type": "tool_call", "server": "t", "tool": "lookup", "arguments": {"ticket_id": "4471"},
             "is_error": True, "latency_ms": 1.0, "text": "'4471' is not a ticket id."},
            {"type": "model", "usage": {"total_tokens": 7}},
        ],
    }
    out = _response(trace)
    assert [s["article_id"] for s in out["sources"]] == ["KB-004"]
    assert out["tickets"] == ["TCK-4410"]
    assert [c["is_error"] for c in out["tool_calls"]] == [False, False, True]
    assert (out["model_turns"], out["total_tokens"]) == (2, 17)


def test_assistant_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import assistant as assistant_module

    with TestClient(app) as client:
        # the suite never starts the MCP servers, so the endpoint reports unavailable
        assert client.post("/api/assistant", json={"message": "hi"}).status_code == 503

        async def fake_ask(message, user):
            return {"answer": f"echo {message}", "tool_calls": [], "sources": [], "tickets": [],
                    "stop_reason": "answered", "model_turns": 1, "total_tokens": 3}

        monkeypatch.setattr(assistant_module.get_assistant(), "ask", fake_ask)
        response = client.post("/api/assistant", json={"message": "status of TCK-4471?"})
        assert response.status_code == 200 and response.json()["answer"] == "echo status of TCK-4471?"


def test_tool_output_is_compacted_and_capped_for_the_model():
    from app.agents.week9.agent import _for_model

    pretty = json.dumps({"passages": [{"text": "x" * 50}]}, indent=2)
    assert _for_model(pretty, None) == pretty  # the CLI agent sends tool output untouched
    compact = _for_model(pretty, 1000)
    assert compact == '{"passages":[{"text":"' + "x" * 50 + '"}]}'
    cut = _for_model("y" * 30, 10)
    assert cut == "y" * 10 + " ...[truncated 20 chars]"
