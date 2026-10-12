"""
Ticket-history MCP server ("server two").

Owner: Support Ops (simulated for Week 9 - in the brief this server is written
and run by another team; here it lives in its own package so it can be bolted
on to the agent by config alone).

Exposes ticket lookup by id and the escalation history behind it:

  list_tickets()                      every ticket, one line each, newest first
  lookup_ticket(ticket_id)            the ticket, the customer, the order and install status
  get_escalation_history(ticket_id)   every escalation step, oldest first

Every caller sees every ticket - there is no per-customer scoping. The host
may attach the signed-in user to each tools/call as request `_meta`:

    {"caller": {"username": "user", "role": "chatbot"}}

It is used only to record WHO asked in the access log. `_meta` is not a tool
argument, so the model never sees it and cannot forge it. Callers that send
none (the Week 9 CLI agent, MCP Inspector, tests) are logged as "unscoped".

Reaches: the ticket exports uploaded as documents - every *.json under DOCS_DIR
with a "tickets" object (and optional "escalations"), merged, re-read on every
call so an upload or delete is live without a restart. Nothing is bundled with
the server; with no export uploaded it has no tickets. The sample export is
sample_documents/tickets/tickets.json.
Logs: one line per call to stderr AND to backend/data/ticket_history_access.log
(timestamp, caller, tool, ticket id, outcome). No model call anywhere in this server.

Run from backend/:
    python -m mcp_servers.ticket_history.server               # stdio
    python -m mcp_servers.ticket_history.server --http 8766   # streamable HTTP
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from app.config import settings

HERE = Path(__file__).resolve().parent
DOCS_DIR = settings.resolved_docs_dir
ACCESS_LOG = HERE.parents[1] / "data" / "ticket_history_access.log"
TICKET_ID = re.compile(r"^TCK-\d{4}$")

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s ticket-history: %(message)s")
logger = logging.getLogger("ticket_history_server")

mcp = FastMCP("support-ops-ticket-history")


def _data() -> dict:
    """Every uploaded ticket export under DOCS_DIR, merged (later files win on a clash)."""
    tickets: dict = {}
    escalations: dict = {}
    files = sorted(p for p in Path(DOCS_DIR).rglob("*.json") if p.is_file()) if Path(DOCS_DIR).is_dir() else []
    for path in files:
        try:
            export = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("skipping %s: %s", path.name, exc)
            continue
        if not isinstance(export, dict) or not isinstance(export.get("tickets"), dict):
            continue
        tickets.update({str(k).upper(): v for k, v in export["tickets"].items()})
        escalations.update({str(k).upper(): v for k, v in (export.get("escalations") or {}).items()})
    return {"tickets": tickets, "escalations": escalations}


def _caller(ctx: Context | None) -> dict | None:
    """The signed-in user the host attached to this call, or None for an unscoped caller."""
    meta = ctx.request_context.meta if ctx is not None else None
    caller = (meta.model_extra or {}).get("caller") if meta is not None else None
    return caller if isinstance(caller, dict) else None


def _who(caller: dict | None) -> str:
    if caller is None:
        return "unscoped"
    return f"{caller.get('username', '?')}/{caller.get('role', '?')}"


def _audit(tool: str, ticket_id: str, outcome: str, caller: dict | None = None) -> None:
    line = (
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} caller={_who(caller)} "
        f"tool={tool} ticket_id={ticket_id} outcome={outcome}"
    )
    logger.info(line)
    try:
        ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ACCESS_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _check_id(tool: str, ticket_id: str, known: dict, caller: dict | None) -> str:
    ticket_id = ticket_id.strip().upper()
    if not TICKET_ID.match(ticket_id):
        _audit(tool, ticket_id, "malformed", caller)
        raise ToolError(f"'{ticket_id}' is not a ticket id. Ticket ids look like TCK-nnnn (e.g. TCK-4471).")
    if not known:
        _audit(tool, ticket_id, "no_ticket_data", caller)
        raise ToolError(
            "No ticket data is available: no ticket export has been uploaded to the document library. "
            "Tell the customer the ticket can't be looked up right now."
        )
    if ticket_id not in known:
        _audit(tool, ticket_id, "not_found", caller)
        raise ToolError(
            f"Ticket {ticket_id} not found in the ticketing system. "
            "Call list_tickets to see the ticket ids that exist, or check the id with the customer."
        )
    return ticket_id


@mcp.tool()
def list_tickets(ctx: Context) -> dict:
    """
    List every support ticket: id, subject, status and last update, newest first.

    Use it when someone asks about a ticket without giving its id ("the refund
    ticket", "the relocation complaint"), or asks which tickets are open; then
    call lookup_ticket on the right one. Never guess a ticket id.
    """
    caller = _caller(ctx)
    tickets = list(_data()["tickets"].values())
    tickets.sort(key=lambda t: t.get("last_update", ""), reverse=True)
    _audit("list_tickets", "*", f"{len(tickets)}_listed", caller)
    return {
        "tickets": [
            {k: t.get(k) for k in ("ticket_id", "subject", "status", "last_update")} for t in tickets
        ]
    }


@mcp.tool()
def lookup_ticket(ticket_id: str, ctx: Context) -> dict:
    """
    Look up a support ticket by its id (format TCK-nnnn).

    Returns the ticket status, contact count, the customer's tier, the order
    (plan, amount paid, payment status) and the installation / activation status.
    Use it whenever a ticket id is mentioned, before saying anything about that
    customer's order, payment or installation.
    """
    caller = _caller(ctx)
    tickets = _data()["tickets"]
    ticket_id = _check_id("lookup_ticket", ticket_id, tickets, caller)
    _audit("lookup_ticket", ticket_id, "found", caller)
    return tickets[ticket_id]


@mcp.tool()
def get_escalation_history(ticket_id: str, ctx: Context) -> dict:
    """
    The escalation history behind a ticket (format TCK-nnnn), oldest first:
    when it was escalated, to which team and level, why, and what happened.

    Use it to see whether a customer was promised a callback or a refund and
    whether that promise was kept. An empty list means it was never escalated.
    """
    caller = _caller(ctx)
    data = _data()
    ticket_id = _check_id("get_escalation_history", ticket_id, data["tickets"], caller)
    history = data["escalations"].get(ticket_id, [])
    _audit("get_escalation_history", ticket_id, f"{len(history)}_events", caller)
    return {"ticket_id": ticket_id, "escalations": history}


def main() -> None:
    parser = argparse.ArgumentParser(description="Support Ops ticket-history MCP server")
    parser.add_argument("--http", type=int, metavar="PORT", help="serve streamable HTTP on this port")
    args = parser.parse_args()
    if args.http:
        mcp.settings.port = args.http
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
