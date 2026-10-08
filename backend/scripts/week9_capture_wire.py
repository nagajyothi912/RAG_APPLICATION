#!/usr/bin/env python3
"""
Capture the raw MCP JSON-RPC exchange with one stdio server: initialize ->
notifications/initialized -> tools/list -> tools/call.

No SDK on the client side - this writes newline-delimited JSON to the server's
stdin and reads its stdout, so what lands in the file is exactly what went over
the wire. Server stderr (its logs) is kept separately and is not protocol.

Usage (from backend/):
    python scripts/week9_capture_wire.py --module mcp_servers.ticket_history.server \
        --call lookup_ticket --args '{"ticket_id": "TCK-4471"}' --out ../docs/week9/wire.raw.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import mcp.types as types

BACKEND = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", required=True, help="server module to run with python -m")
    parser.add_argument("--call", required=True, help="tool name for tools/call")
    parser.add_argument("--args", default="{}", help="JSON arguments for tools/call")
    parser.add_argument("--out", required=True)
    opts = parser.parse_args()

    proc = subprocess.Popen(
        [sys.executable, "-m", opts.module],
        cwd=BACKEND,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    exchange: list[dict] = []

    def send(message: dict) -> None:
        line = json.dumps(message)
        exchange.append({"direction": "client -> server", "raw": line, "message": message})
        proc.stdin.write(line + "\n")
        proc.stdin.flush()

    def receive() -> dict:
        line = proc.stdout.readline()
        if not line:
            raise SystemExit("server closed stdout:\n" + proc.stderr.read())
        message = json.loads(line)
        exchange.append({"direction": "server -> client", "raw": line.rstrip("\n"), "message": message})
        return message

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": types.LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "week9-wire-capture", "version": "1.0"},
            },
        }
    )
    receive()
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    receive()
    send(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": opts.call, "arguments": json.loads(opts.args)},
        }
    )
    receive()

    proc.stdin.close()
    stderr = proc.stderr.read()
    proc.wait(timeout=10)

    Path(opts.out).write_text(
        json.dumps(
            {
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "server_command": f"python -m {opts.module}",
                "transport": "stdio (newline-delimited JSON-RPC 2.0 on stdin/stdout)",
                "exchange": exchange,
                "server_stderr_not_protocol": stderr.splitlines(),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        "utf-8",
    )
    print(f"{len(exchange)} messages written to {opts.out}")


if __name__ == "__main__":
    main()
