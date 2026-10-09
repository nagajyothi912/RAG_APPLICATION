"""A minimal stdio MCP server for the Week 9 host tests - no model, no RAG."""

import sys

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

# Named from argv when run as a subprocess; imported in-process (where argv is
# pytest's) it is always "echo".
mcp = FastMCP(sys.argv[1] if __name__ == "__main__" and len(sys.argv) > 1 else "echo")


@mcp.tool()
def echo(text: str) -> str:
    """Return the text unchanged."""
    return text


@mcp.tool()
def whoami(ctx: Context) -> str:
    """Return the caller the host attached as request _meta, or 'nobody'."""
    meta = ctx.request_context.meta
    return str((meta.model_extra or {}).get("caller", "nobody")) if meta is not None else "nobody"


@mcp.tool()
def fail(reason: str = "broken") -> str:
    """Always fails, with the given reason."""
    raise ToolError(f"failed: {reason}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
