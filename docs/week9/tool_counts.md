# Requirement 3 — tools discovered before → after

**2 before → 4 after:** before = `search_help_centre`, `get_article`; after = `search_help_centre`, `get_article`, `lookup_ticket`, `get_escalation_history` (new: `lookup_ticket`, `get_escalation_history`).

These come from what each server answered to `tools/list` during a real agent run, not from notes. The agent records its discovery in every trace (`discovery` block):

- **Before** (`evidence/trace_server1.json`, tag `w9-server1`, one server in the config):
  - `help-centre` (airfiber-help-centre, stdio, protocol 2025-11-25): `search_help_centre`, `get_article`
- **After** (`evidence/trace_server1_plus_2.json`, tag `w9-server1+2`, the config gained one entry):
  - `help-centre` (airfiber-help-centre, stdio, protocol 2025-11-25): `search_help_centre`, `get_article`
  - `ticket-history` (support-ops-ticket-history, stdio, protocol 2025-11-25): `lookup_ticket`, `get_escalation_history`

Re-check without calling the model:

```bash
cd backend
git checkout w9-server1 -- config/mcp_servers.json && python -m app.agents.week9.agent --list-tools
git checkout HEAD -- config/mcp_servers.json        && python -m app.agents.week9.agent --list-tools
```

The raw `tools/list` response from the ticket-history server is step 5 of [wire.json](wire.json).
