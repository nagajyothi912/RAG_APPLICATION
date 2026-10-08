"""A minimal stdio MCP server for the Week 9 host tests - no model, no RAG."""

import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

mcp = FastMCP(sys.argv[1] if len(sys.argv) > 1 else "echo")


@mcp.tool()
def echo(text: str) -> str:
    """Return the text unchanged."""
    return text


@mcp.tool()
def fail(reason: str = "broken") -> str:
    """Always fails, with the given reason."""
    raise ToolError(f"failed: {reason}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
