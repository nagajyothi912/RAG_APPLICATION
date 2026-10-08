"""
Help-centre MCP server ("server one") - the capability this app owns.

Exposes the AirFiber help centre over MCP so any agent can search it:

  search_help_centre(query, product_area?, top_k?)  hybrid retrieval, cited passages
  get_article(article_id)                           one whole article by its KB id

It wraps RagService.retrieve - retrieval only. There is deliberately NO model
call in here: an MCP server exposes a capability, and the host that connects to
it runs the model. RagService.ask (which calls Groq) is never used.

Run from backend/:
    python -m mcp_servers.help_centre.server                 # stdio (what the agent config uses)
    python -m mcp_servers.help_centre.server --http 8765     # streamable HTTP, for other people's agents

stdout is the JSON-RPC channel under stdio, so every log line goes to stderr.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s help-centre: %(message)s",
)
logger = logging.getLogger("help_centre_server")

mcp = FastMCP("airfiber-help-centre")

_service = None


def service():
    """The RagService, built once. Importing it loads MiniLM and indexes DOCS_DIR."""
    global _service
    if _service is None:
        from app.services.rag_service import get_rag_service

        _service = get_rag_service()
        logger.info("indexed %d chunks from %s", len(_service.store.chunks), _service_docs_dir())
    return _service


def _service_docs_dir() -> str:
    from app.config import settings

    return str(settings.resolved_docs_dir)


@mcp.tool()
def search_help_centre(query: str, product_area: str | None = None, top_k: int = 5) -> dict:
    """
    Search the AirFiber help centre and return the passages that best match the query.

    Use this for any question about AirFiber plans, prices, billing, refunds,
    installation, router LEDs and error codes, or account changes. Answer only
    from the passages returned, and cite their article_id.

    Args:
        query: The customer's question or the facts you need, in plain words.
            Include exact identifiers when you have them (plan names like
            AirFiber_1199_1M, error codes, LED colours) - they are matched by keyword too.
        product_area: Optional filter - one of the areas listed in `available_areas`
            of any result (e.g. plans, billing, installation, troubleshooting, account).
            Leave empty to search everything.
        top_k: How many passages to return, 1-10.
    """
    svc = service()
    areas = svc.product_areas()
    if product_area and product_area not in areas:
        raise ToolError(
            f"product_area '{product_area}' does not exist. Use one of {areas}, "
            "or leave product_area empty to search all areas."
        )
    top_k = max(1, min(int(top_k), 10))
    filters = {"product_area": product_area} if product_area else None
    results = svc.retrieve(query, top_k=top_k, filters=filters, mode="week4")
    logger.info("search_help_centre query=%r area=%s -> %d passages", query, product_area, len(results))
    return {
        "query": query,
        "available_areas": areas,
        "passages": [
            {
                "article_id": chunk.article_id,
                "source_file": chunk.source,
                "section": chunk.section,
                "product_area": chunk.product_area,
                "last_updated": chunk.last_updated,
                "relevance": round(float(scored.dense_score), 4),
                "text": chunk.text,
            }
            for chunk, scored in results
        ],
    }


def _not_found_message(article_id: str, known: dict[str, str]) -> str:
    """Say what was wrong, what a valid id looks like, and which ids exist - enough to fix the call."""
    digits = re.sub(r"\D", "", article_id)
    guess = f"KB-{int(digits):03d}" if digits else None
    hint = f" Did you mean {guess}?" if guess in known else ""
    listing = "; ".join(f"{kb} ({title})" for kb, title in sorted(known.items()))
    return (
        f"article '{article_id}' not found: article ids look like KB-nnn with three digits, "
        f"e.g. KB-004 (not KB-4).{hint} Valid ids: {listing}. "
        "Call get_article again with one of these, or use search_help_centre if you don't know the id."
    )


@mcp.tool()
def get_article(article_id: str) -> dict:
    """
    Fetch one complete help-centre article by its id, e.g. KB-004.

    Use this when you already know which article you need: the customer quotes an
    article id, or a search_help_centre passage cites one and you need the whole
    article (every section, full tables) instead of a single passage. If you do not
    know the id, call search_help_centre first.

    Args:
        article_id: 'KB-' followed by exactly three digits, zero-padded - KB-004,
            not KB-4, kb4 or "article 4". Customers often shorten ids; pad them
            before calling.

    If the id does not exist, the error lists every valid id with its title.
    Pick the right one and call again; do not retry the same id.
    """
    svc = service()
    chunks = sorted(
        (chunk for chunk in svc.store.chunks if chunk.article_id == article_id),
        key=lambda chunk: chunk.chunk_id,
    )
    if not chunks:
        logger.info("get_article %r -> not found", article_id)
        known = {chunk.article_id: chunk.title for chunk in svc.store.chunks if chunk.article_id}
        raise ToolError(_not_found_message(article_id, known))
    first = chunks[0]
    logger.info("get_article %r -> %d chunks", article_id, len(chunks))
    return {
        "article_id": article_id,
        "title": first.title,
        "source_file": first.source,
        "product_area": first.product_area,
        "last_updated": first.last_updated,
        "text": "\n\n".join(chunk.text for chunk in chunks),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--http", type=int, metavar="PORT", help="serve streamable HTTP on this port")
    args = parser.parse_args()
    service()  # index before the first request, not inside it
    if args.http:
        mcp.settings.port = args.http
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
