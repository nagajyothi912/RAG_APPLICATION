"""
Ticket-history MCP server ("server two").

Owner: Support Ops (simulated for Week 9 - in the brief this server is written
and run by another team; here it lives in its own package with its own data so
it can be bolted on to the agent by config alone).

Exposes ticket lookup by id and the escalation history behind it:

  lookup_ticket(ticket_id)            the ticket, the customer, the order and install status
  get_escalation_history(ticket_id)   every escalation step, oldest first

Reaches: tickets.json next to this file (stands in for the ticketing system).
Logs: one line per call to stderr AND to backend/data/ticket_history_access.log
(timestamp, tool, ticket id). There is no caller identity on stdio, so the log
cannot say WHO asked. No model call anywhere in this server.

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

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "tickets.json"
ACCESS_LOG = HERE.parents[1] / "data" / "ticket_history_access.log"
TICKET_ID = re.compile(r"^TCK-\d{4}$")

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s ticket-history: %(message)s")
logger = logging.getLogger("ticket_history_server")

mcp = FastMCP("support-ops-ticket-history")


def _data() -> dict:
    return json.loads(DATA_FILE.read_text("utf-8"))


def _audit(tool: str, ticket_id: str, outcome: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} tool={tool} ticket_id={ticket_id} outcome={outcome}"
    logger.info(line)
    try:
        ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ACCESS_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _check_id(tool: str, ticket_id: str, known: dict) -> str:
    ticket_id = ticket_id.strip().upper()
    if not TICKET_ID.match(ticket_id):
        _audit(tool, ticket_id, "malformed")
        raise ToolError(f"'{ticket_id}' is not a ticket id. Ticket ids look like TCK-nnnn (e.g. TCK-4471).")
    if ticket_id not in known:
        _audit(tool, ticket_id, "not_found")
        raise ToolError(f"Ticket {ticket_id} not found in the ticketing system. Check the id with the customer.")
    return ticket_id


@mcp.tool()
def lookup_ticket(ticket_id: str) -> dict:
    """
    Look up a support ticket by its id (format TCK-nnnn).

    Returns the ticket status, contact count, the customer's tier, the order
    (plan, amount paid, payment status) and the installation / activation status.
    Use it whenever a ticket id is mentioned, before saying anything about that
    customer's order, payment or installation.
    """
    tickets = _data()["tickets"]
    ticket_id = _check_id("lookup_ticket", ticket_id, tickets)
    _audit("lookup_ticket", ticket_id, "found")
    return tickets[ticket_id]


@mcp.tool()
def get_escalation_history(ticket_id: str) -> dict:
    """
    The escalation history behind a ticket (format TCK-nnnn), oldest first:
    when it was escalated, to which team and level, why, and what happened.

    Use it to see whether a customer was promised a callback or a refund and
    whether that promise was kept. An empty list means it was never escalated.
    """
    data = _data()
    ticket_id = _check_id("get_escalation_history", ticket_id, data["tickets"])
    history = data["escalations"].get(ticket_id, [])
    _audit("get_escalation_history", ticket_id, f"{len(history)}_events")
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
