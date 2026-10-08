"""
The MCP side of the Week 9 agent: connect to every server in a config file,
discover their tools, and route calls back to whichever server owns each tool.

Nothing here knows any server or tool by name. Adding a server is an edit to
the config file (backend/config/mcp_servers.json), never to this module - the
Week 9 "bolt on a server without touching the agent" requirement.

Config format (the same shape Claude Desktop and most MCP hosts use):

    {
      "mcpServers": {
        "<name>": {"command": "${PYTHON}", "args": ["-m", "pkg.server"], "cwd": "..", "env": {}},
        "<name>": {"url": "http://host:port/mcp", "headers": {"Authorization": "Bearer ..."}}
      }
    }

`${PYTHON}` is replaced with this interpreter, and a relative `cwd` is resolved
against the config file's folder, so the config works on any checkout.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.client.streamable_http import streamablehttp_client

_TOOL_NAME_OK = re.compile(r"[^a-zA-Z0-9_-]")


@dataclass
class ServerConfig:
    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class DiscoveredTool:
    server: str
    name: str  # the name the model sees (unique across servers)
    remote_name: str  # the name the server knows it by
    description: str
    input_schema: dict


@dataclass
class ToolOutcome:
    server: str
    tool: str
    arguments: dict
    is_error: bool
    text: str
    latency_ms: float


def load_config(path: str | Path) -> list[ServerConfig]:
    path = Path(path).resolve()
    raw = json.loads(path.read_text("utf-8"))
    servers = []
    for name, entry in raw.get("mcpServers", {}).items():
        if entry.get("disabled"):
            continue
        command = entry.get("command")
        if command == "${PYTHON}":
            command = sys.executable
        cwd = entry.get("cwd")
        if cwd and not Path(cwd).is_absolute():
            cwd = str((path.parent / cwd).resolve())
        servers.append(
            ServerConfig(
                name=name,
                command=command,
                args=list(entry.get("args", [])),
                env=dict(entry.get("env", {})),
                cwd=cwd,
                url=entry.get("url"),
                headers=dict(entry.get("headers", {})),
            )
        )
    return servers


def _content_text(result: Any) -> str:
    parts = []
    for item in result.content or []:
        text = getattr(item, "text", None)
        parts.append(text if text is not None else json.dumps(item.model_dump(mode="json")))
    if not parts and getattr(result, "structuredContent", None) is not None:
        parts.append(json.dumps(result.structuredContent))
    return "\n".join(parts)


class McpHost:
    """Async context manager holding one MCP client session per configured server."""

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.servers = load_config(self.config_path)
        self.tools: dict[str, DiscoveredTool] = {}
        self.server_info: dict[str, dict] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "McpHost":
        try:
            for server in self.servers:
                await self._connect(server)
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    async def _connect(self, server: ServerConfig) -> None:
        if server.url:
            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(server.url, headers=server.headers or None)
            )
        else:
            if not server.command:
                raise ValueError(f"MCP server '{server.name}' needs either 'command' or 'url'.")
            params = StdioServerParameters(
                command=server.command,
                args=server.args,
                env={**get_default_environment(), **{k: os.path.expandvars(v) for k, v in server.env.items()}},
                cwd=server.cwd,
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        init = await session.initialize()
        self._sessions[server.name] = session
        self.server_info[server.name] = {
            "server_name": init.serverInfo.name,
            "server_version": init.serverInfo.version,
            "protocol_version": str(init.protocolVersion),
            "transport": "streamable-http" if server.url else "stdio",
        }

        cursor = None
        while True:
            listed = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
            for tool in listed.tools:
                self._register(server.name, tool)
            cursor = listed.nextCursor
            if not cursor:
                break

    def _register(self, server: str, tool: Any) -> None:
        name = _TOOL_NAME_OK.sub("_", tool.name)
        if name in self.tools:  # two servers exposing the same name: namespace the newcomer
            name = _TOOL_NAME_OK.sub("_", f"{server}__{tool.name}")
        self.tools[name] = DiscoveredTool(
            server=server,
            name=name,
            remote_name=tool.name,
            description=(tool.description or "").strip(),
            input_schema=tool.inputSchema or {"type": "object", "properties": {}},
        )

    def discovery(self) -> dict:
        """What tools/list returned, per server - the before/after tool count comes from here."""
        per_server = {
            name: {**self.server_info[name], "tools": [t.remote_name for t in self.tools.values() if t.server == name]}
            for name in self._sessions
        }
        return {
            "config": str(self.config_path),
            "servers": per_server,
            "tool_count": len(self.tools),
            "tool_names": list(self.tools),
        }

    def openai_tools(self) -> list[dict]:
        """The discovered tools in the function-calling shape Groq's API expects."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self.tools.values()
        ]

    async def call(self, name: str, arguments: dict) -> ToolOutcome:
        tool = self.tools.get(name)
        if tool is None:
            return ToolOutcome(
                server="(host)",
                tool=name,
                arguments=arguments,
                is_error=True,
                text=f"No tool named '{name}'. Available tools: {sorted(self.tools)}.",
                latency_ms=0.0,
            )
        started = time.perf_counter()
        result = await self._sessions[tool.server].call_tool(tool.remote_name, arguments)
        return ToolOutcome(
            server=tool.server,
            tool=tool.remote_name,
            arguments=arguments,
            is_error=bool(result.isError),
            text=_content_text(result),
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
