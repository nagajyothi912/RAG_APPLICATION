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
            assert discovery["tool_count"] == 4
            assert discovery["servers"]["one"]["tools"] == ["echo", "fail"]
            # the second server's identical names are namespaced, not dropped
            assert set(host.tools) == {"echo", "fail", "two__echo", "two__fail"}
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
    assert [t["function"]["name"] for t in completions.requests[0]["tools"]] == ["echo", "fail"]
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
