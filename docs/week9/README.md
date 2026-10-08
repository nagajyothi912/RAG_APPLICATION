# Week 9 — Task Set A submission: bolt on the ticket-history server without touching the agent

Full explanation: [WEEK9_GUIDE.md](WEEK9_GUIDE.md). Brief: [../assignments/W9-Task-Set-A.md](../assignments/W9-Task-Set-A.md).

## Checklist

| Deliverable | File | Headline |
| --- | --- | --- |
| `agent_diff.txt`: 0 changed lines in the agent module | [agent_diff.txt](agent_diff.txt) | `git diff w9-server1 w9-server1+2 -- backend/app/agents/week9/` is empty. Only the config and the new server package changed. |
| Config diff adding the second server | [config_diff.txt](config_diff.txt) | +5 lines in `backend/config/mcp_servers.json` |
| One query that provably calls a server-two tool | [evidence/trace_server1_plus_2.json](evidence/trace_server1_plus_2.json) | `tools_called`: `ticket-history.lookup_ticket`, `ticket-history.get_escalation_history`, then 3 × `help-centre.search_help_centre` |
| `wire.json`: raw initialize → tools/list → tools/call, annotated | [wire.json](wire.json) (byte-exact lines in [evidence/wire.raw.json](evidence/wire.raw.json)) | The model call happens only in the host (`agent.py` → Groq), never in the MCP client or server |
| Tool count before → after, with names, from `tools/list` | [tool_counts.md](tool_counts.md) | **2 → 4**: `search_help_centre`, `get_article` → plus `lookup_ticket`, `get_escalation_history` |
| `error_before_after.md`: same failing call, old vs new | [error_before_after.md](error_before_after.md) | Same seeded `get_article("KB-4")`. Before: gave up on the tool, 2 fallback searches, 7,328 tokens. After: corrected to `KB-004` next turn, 3,451 tokens. |
| `risk_note.md`: exactly 5 lines | [risk_note.md](risk_note.md) | Don't ship as-is: no auth in HTTP mode, no caller in the audit log, full customer PII reachable |

## The commits the evidence points at

| Tag / commit | What it is |
| --- | --- |
| `w9-server1` (`f6e3330`) | Agent module frozen here; config lists server one only. `get_article` still has the "before" docstring and `Error 3`. |
| `w9-server1+2` (`a592f55`) | Ticket-history server package + one config entry. Agent module untouched. |
| `cd36312` | `get_article` docstring rewritten as a prompt; recoverable not-found error (requirement 5, on our own server). |

Every run used `openai/gpt-oss-120b` on Groq at temperature 0. Each figure comes from a single run, so read the before/after differences as direction, not as a measured average.

## Reproduce

```bash
cd backend
pip install -r requirements.txt                      # adds mcp>=1.10,<2
python -m app.agents.week9.agent --list-tools        # discovery only, no model call
python -m app.agents.week9.agent "Ticket TCK-4471 - customer asks whether they get their 1999 back. Check the ticket and its escalation history and draft the reply."
python scripts/week9_capture_wire.py --module mcp_servers.ticket_history.server \
  --call lookup_ticket --args '{"ticket_id": "TCK-4471"}' --out /tmp/wire.raw.json
git diff w9-server1 w9-server1+2 -- app/agents/week9/  # prints nothing
pytest tests/test_week9_mcp.py -v                    # 8 tests, no Groq calls
```

The bonus (a gateway with an audit line per call and a scoped token) is **not** done; see [WEEK9_GUIDE.md §7](WEEK9_GUIDE.md#7-what-is-not-implemented--limitations).
