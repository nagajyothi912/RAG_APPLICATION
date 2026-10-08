# Week 9 — MCP: the agent discovers its tools, and a second server is bolted on by config alone

> **In one sentence:** the ticket agent no longer has a hard-coded tool list. It asks MCP servers what tools they offer, so adding the Support Ops ticket-history server took one config entry and **zero changed lines** in the agent.
>
> **TL;DR:** Week 9 builds a new agent (`backend/app/agents/week9/`). At startup it reads `backend/config/mcp_servers.json`, connects to each server, runs the MCP handshake, calls `tools/list`, and hands those tools to the model. We wrapped our own help-centre search as **server one**, froze the agent at tag `w9-server1`, then added a **ticket-history server** as **server two** by editing only the config: 2 tools → 4 tools, and the agent's git diff is empty. We captured the raw JSON-RPC messages, and rewrote one tool's docstring and error message on our own server. On the same failing call, the model went from abandoning the tool (7,328 tokens) to fixing its call on the next turn (3,451 tokens). The gateway bonus is not done.

Brief: [../assignments/W9-Task-Set-A.md](../assignments/W9-Task-Set-A.md) (Task Set A). The module brief (*MCP — the Standard Way Agents Reach Tools & Data*) was provided as a PDF and isn't in the repo. Submission index: [README.md](README.md).

---

## 1. The problem in plain words

Until Week 8, every tool the ticket agent could use was written into its code. `ticket_reply_app/agent.py` imports `TOOL_SCHEMAS` from `tools.py`. Adding a tool meant editing the agent and releasing new code, and no other team could reuse those tools.

**MCP (Model Context Protocol)** is a standard "socket" between an AI app and tools. A tool provider runs an **MCP server**. Any app that speaks MCP can connect to it, ask what it offers, and call it. The app doesn't need to know the tools in advance.

Week 9's scenario: Support Ops built a ticket-history MCP server and wants the agent using it *this afternoon*, with no code release. That's only possible if the agent truly discovers its tools. The task is to **prove** that: show the agent's code didn't change, show the raw protocol messages, count the tools from the server's own answer, improve one tool's error message, and judge whether the third-party server is safe to trust.

**MCP doesn't make the model smarter.** It's plumbing: tools become reusable and easy to swap. Our own run shows this ([§6.5](#65-what-mcp-did-not-fix)).

---

## 2. Requirements

There was no separate requirements document for the base build. It comes from the module brief (PDF); Task Set A comes from [W9-Task-Set-A.md](../assignments/W9-Task-Set-A.md).

| # | Requirement | Status | Where |
| --- | --- | --- | --- |
| Base | Agent discovers tools over MCP instead of hard-coding them | ✅ | [agent.py](../../backend/app/agents/week9/agent.py), [mcp_host.py](../../backend/app/agents/week9/mcp_host.py) |
| Base | Your own MCP server exposing one real capability of the app | ✅ | [help_centre/server.py](../../backend/mcp_servers/help_centre/server.py): hybrid help-centre retrieval |
| Base | Another person's agent can call it | ✅ technically; ⚠️ not yet tried by a classmate | Both servers also serve streamable HTTP (`--http PORT`), and we tested that through the same agent with a URL-only config |
| A1 | Add ticket-history server via config; one query provably calls its tool | ✅ | [config_diff.txt](config_diff.txt), [trace_server1_plus_2.json](evidence/trace_server1_plus_2.json) |
| A2 | Git diff: zero lines changed in the agent module | ✅ | [agent_diff.txt](agent_diff.txt) |
| A3 | Tool count before → after, with names, from `tools/list` | ✅ | [tool_counts.md](tool_counts.md): **2 → 4** |
| A4 | Raw initialize → tools/list → tools/call, every top-level field annotated, model-call location stated | ✅ | [wire.json](wire.json) |
| A5 | Docstring-as-prompt + recoverable error on **our own** server, before/after transcript | ✅ | [error_before_after.md](error_before_after.md) |
| A6 | 5-line supply-chain risk note | ✅ | [risk_note.md](risk_note.md) |
| Bonus | Gateway, one audit line per call, scoped token denying escalation history | ❌ | — |

---

## 3. Concepts covered

| Concept | Plain explanation | In this repo |
| --- | --- | --- |
| **Host, client, server** | The **host** is the app that runs the AI model. For each server it holds one **client**, a connection that speaks MCP. A **server** offers capabilities and never runs the model. | Host = `agent.py`. Clients = the `ClientSession`s in `mcp_host.py`. Servers = `mcp_servers/help_centre`, `mcp_servers/ticket_history`. |
| **Where the AI runs** | Only in the host. The server doesn't know which model, if any, is calling it. | The only Groq call is `client.chat.completions.create` in `agent.py`. Server one wraps `RagService.retrieve` and deliberately not `RagService.ask`, which would call Groq. |
| **Tools, resources, prompts** | Three things a server can offer. **Tools** are actions the *model* chooses to call. **Resources** are data the *app* chooses to attach. **Prompts** are templates a *user* picks. | All four of our capabilities are tools. See [§6.4](#64-tool-or-resource-the-escalation-history-decision). |
| **JSON-RPC 2.0** | The message format MCP uses. A request has `jsonrpc`, `id`, `method`, `params`; the response echoes the `id` and carries `result` *or* `error`; a **notification** has no `id` and gets no reply. | Every field annotated in [wire.json](wire.json) |
| **Lifecycle / handshake** | `initialize`, where each side states its protocol version and capabilities, then `notifications/initialized`, then normal traffic. | Steps 1–3 of wire.json; protocol version `2025-11-25` |
| **Tool discovery** | `tools/list` returns each tool's `name`, `description` and `inputSchema` (JSON Schema of its arguments). The agent turns these into the model's function definitions at runtime. | `McpHost._connect` / `openai_tools()` |
| **Transports** | How the messages travel. **stdio**: the host starts the server as a child process and they exchange one JSON message per line over stdin/stdout. **Streamable HTTP**: the server listens on a URL, so it can run anywhere. | Config uses stdio (`command`/`args`); `--http PORT` + `"url"` in config for HTTP |
| **Docstring = prompt** | FastMCP turns a Python function's docstring into the tool `description` and its type hints into `inputSchema`. The model reads that description to decide when and how to call the tool, so it's prompt engineering. | `get_article` before ("Get article.") vs after |
| **Recoverable errors** | When a tool fails it should return a normal result with `isError: true` and a message the model can act on: what was wrong, what's valid, what to do next. A JSON-RPC `error` means the protocol itself failed. | `_not_found_message` in server one; `_check_id` in server two |
| **Supply-chain / trust boundary** | A third-party server runs inside your agent's trust boundary. It sees what its credentials see, its descriptions and outputs flow into your model's context, and you're responsible for what it can reach and log. | [risk_note.md](risk_note.md) |

---

## 4. What was implemented

```
                  HOST — backend/app/agents/week9/  (the ONLY place a model is called)
 ticket text ─►  agent.py   ReAct loop: model ⇄ tools, until it writes the reply  ──► Groq (gpt-oss-120b)
                    │
                 mcp_host.py  reads config/mcp_servers.json → one ClientSession per server
                    │         initialize → tools/list → map tool name → owning server
          ┌─────────┴───────────────────────────┐   JSON-RPC 2.0 over stdio (or streamable HTTP)
          ▼                                     ▼
  SERVER ONE (ours)                       SERVER TWO ("Support Ops")
  mcp_servers/help_centre/server.py       mcp_servers/ticket_history/server.py
   search_help_centre(query, area?, k?)    lookup_ticket(ticket_id)
   get_article(article_id)                 get_escalation_history(ticket_id)
   → RagService.retrieve (BM25+dense,      → its own tickets.json; audit line per call
     RRF, rerank) — no Groq                  to stderr + data/ticket_history_access.log
```

The pieces:

- **`mcp_host.py`** has no server or tool names in it. A test fails if one appears.
  - **Config:** it loads the config format most MCP hosts use (`{"mcpServers": {...}}`). `${PYTHON}` is replaced with the current interpreter, and a relative `cwd` resolves against the config file's folder.
  - **Connecting:** each server is connected over stdio (`command`/`args`) or streamable HTTP (`url`). It runs `initialize`, then reads `tools/list`, following page cursors.
  - **Name clashes:** if two servers offer the same tool name, the second gets a `server__tool` prefix.
  - **What it reports:** `discovery()` returns what each server reported, and the before/after tool counts are taken from that.
- **`agent.py`**: the ReAct loop. Its system prompt is generic ("your tools were discovered at runtime… if a tool returns an error, read the message…").
  - **Trace:** every run writes a full trace: discovery, each model turn with token usage, each tool call with server, tool, arguments, `isError` and the returned text, the final reply, and `tools_called`.
  - **`--seed-call`:** a fixed tool call can be replayed as the agent's first move. That's how both requirement 5 runs handled *the same* failing call.
- **Server one** is the app's real capability, the Week 3/4 retrieval stack (`mode="week4"`), returning passages with `article_id`, section and a relevance score. It indexes `DOCS_DIR` on startup, which loads MiniLM, so each spawn takes about 14 s.
- **Server two** is written as a separate team's package with its own data (fictional customers mapped onto the Week 7 tickets: TCK-4471 ≈ T017, TCK-4410 ≈ T010, and so on).
  - **Id checks:** it validates ticket ids (`TCK-nnnn`) and separates *malformed* from *not found*.
  - **Audit log:** it writes one line per call.
- **`scripts/week9_capture_wire.py`** speaks raw JSON-RPC to a server over a pipe, with no SDK on the client side, so the capture is exactly what was sent.
- **`tests/test_week9_mcp.py`** has 8 tests, none of which call Groq:
  - the no-hard-coded-names guard
  - config loading
  - discovery, routing and namespacing against a fixture server
  - the agent loop with a scripted fake model
  - the seeded call
  - both servers' tools through in-memory MCP sessions
  - the recoverable message
  - the server-two audit log

**SDK choice.** `pip install mcp` now installs **2.x**, which renamed FastMCP to `MCPServer` and changed other APIs. The brief and almost all course material use FastMCP, so `requirements.txt` pins `mcp>=1.10,<2` (installed 1.30.0, protocol `2025-11-25`). We checked the package's provenance first: Model Context Protocol, a Series of LF Projects; repo `modelcontextprotocol/python-sdk`.

---

## 5. How the evidence was produced (in commit order)

| Step | Commit / tag | Evidence |
| --- | --- | --- |
| 1. Agent + host + server one; `get_article` in its bad "before" form; config lists one server. Run a help-centre question. | `f6e3330` = **`w9-server1`** | `evidence/trace_server1.json`: 2 tools discovered; called `help-centre.search_help_centre`; answered citing KB-004 |
| 2. Add the ticket-history package + one config entry. Run a TCK-4471 ticket. | `a592f55` = **`w9-server1+2`** | `agent_diff.txt` (empty), `config_diff.txt`, `evidence/trace_server1_plus_2.json` (4 tools; called `ticket-history.lookup_ticket`, `ticket-history.get_escalation_history`) |
| 3. Capture the raw exchange with server two. | (state of step 2) | `evidence/wire.raw.json`, annotated into `wire.json` |
| 4. "Before" error runs: seeded and unseeded `KB-4`. | (state of step 2) | `evidence/error_before_*.json` |
| 5. Rewrite `get_article`'s docstring and error; "after" runs. | `cd36312` | `evidence/error_after_*.json`, `error_before_after.md` |

All model runs: `openai/gpt-oss-120b` on Groq, temperature 0.

---

## 6. Analysis & results

### 6.1 Zero-line agent diff (requirement 2, 30 marks)

`git diff w9-server1 w9-server1+2 -- backend/app/agents/week9/` prints nothing. What did change: `backend/config/mcp_servers.json` (+5 lines) and the new `backend/mcp_servers/ticket_history/` package (3 files). The agent can't secretly know about the new server, because `test_agent_module_names_no_server_or_tool` fails if any server name, tool name or `TCK-` id appears in the agent module. While building it, that test caught two real leaks: an example ticket id in a docstring, and the phrase "help-centre" in the system prompt. Both were removed before the freeze.

### 6.2 Tool discovery (requirements 1 and 3)

**2 → 4 tools**, read from `tools/list`: `search_help_centre`, `get_article` → plus `lookup_ticket`, `get_escalation_history`. On the TCK-4471 ticket the agent called `lookup_ticket` → `get_escalation_history` → `search_help_centre` ×3 and wrote a reply naming the customer, the missed 2026-09-04 slot and the ₹1,999 payment. All of that came from server two, which the agent had never been told about.

### 6.3 Recoverable error (requirement 5)

| Run (same failing call `get_article("KB-4")`) | Tool calls | Failed | Tokens | Read the article? |
| --- | ---: | ---: | ---: | --- |
| Before (`Error 3`), seeded | 3 | 1 | 7,328 | no: abandoned the tool, searched twice |
| After (recoverable message), seeded | 2 | 1 | 3,451 | yes: corrected to `KB-004` next turn |
| Before, unseeded | 3 | 1 | 7,178 | no: made the `KB-4` mistake itself |
| After, unseeded | 1 | 0 | 3,067 | yes: docstring alone made it pad the id |

The before model wasn't stupid. `Error 3` gave it nothing to work with, so it couldn't tell a bad id from a missing article or a dead server. The after message names the format, suggests `KB-004`, and lists every valid id, and the model used it at once. The docstring change mattered even more than the error change: unseeded, the failure didn't happen at all. **Caveat:** each row is one run (n = 1). The direction is clear, but these aren't averages.

### 6.4 Tool or resource? The escalation-history decision

The brief warns that escalation history might be *context the app should attach* (a resource) rather than something the model fetches (a tool). We kept it a **tool**, for these reasons:

- **The model needs it only sometimes.** It needs the history for refund, callback and delay disputes, and the TCK-4471 run fetched it in one call. For "what does my orange LED mean?" it's irrelevant, and attaching it to every prompt would waste context.
- **The bonus assumes it's a tool.** It asks for a token that *denies* it, which only makes sense for a tool.

The counter-argument: when the app already knows the ticket id, attaching `ticket://TCK-4471/escalations` as a resource would save the model a turn. In production that's the better design for ticket-scoped chats.

### 6.5 What MCP did not fix

The TCK-4471 reply says *"I've opened a priority reschedule for you"*. No tool did that, and the agent has no tool that can. It also denies the refund by reading the slow-speed refund rule, though the installation never happened. MCP gave the agent new **data**, not better **judgement**. The Week 7/8 lessons (trajectory checks, output guardrails) still apply on top of MCP.

---

## 7. What is NOT implemented / limitations

- **Bonus not done:** no gateway process, no single audit line with *caller* identity, no scoped token. Server two's audit log records tool, ticket id and outcome but no caller, because stdio has no identity.
- **Server two is simulated by us**, not written by another team. It sits in its own package with its own data, so the config-only addition is real, but the supply-chain story is staged. Swapping servers with a Track A classmate would make this stronger, and would also cover "someone else's agent calls your server".
- **No authentication on either server's HTTP mode.** It's fine on localhost, but don't expose the ports.
- **Server one starts slowly** (about 14 s per spawn, to load MiniLM and index 30 chunks), and every agent run spawns it again.
- **Results are single runs at temperature 0** (n = 1 per row).
- **The Week 9 agent is separate from the Week 7/8 agent,** so those weeks' results stay reproducible. It has no budgets (iterations only, max 8) and no output guardrail.
- **Not in the web UI.** The admin console has no Week 9 tab; everything runs from the command line.

---

## 8. How to run & verify

```bash
cd backend
pip install -r requirements.txt                      # mcp>=1.10,<2

# discovery only (no model call): prints servers, protocol version, tool names, tool count
python -m app.agents.week9.agent --list-tools

# a full run; the trace shows which server each tool call went to
python -m app.agents.week9.agent --out /tmp/trace.json \
  "Ticket TCK-4471 - customer asks whether they get their 1999 back. Check the ticket and its escalation history and draft the reply."

# the zero-line proof
git diff w9-server1 w9-server1+2 -- app/agents/week9/      # prints nothing
git diff --stat w9-server1 w9-server1+2                    # config + new server only

# raw protocol capture against server two
python scripts/week9_capture_wire.py --module mcp_servers.ticket_history.server \
  --call lookup_ticket --args '{"ticket_id": "TCK-4471"}' --out /tmp/wire.raw.json

# inspect a server interactively (needs Node): MCP Inspector
npx @modelcontextprotocol/inspector python -m mcp_servers.ticket_history.server

# serve over HTTP for someone else's agent, then point a config at it:
python -m mcp_servers.help_centre.server --http 8765
#   {"mcpServers": {"airfiber": {"url": "http://<your-ip>:8765/mcp"}}}

pytest tests/test_week9_mcp.py -v                          # 8 tests, no Groq calls
```

Server one indexes whatever is in `backend/data/docs`. Upload the sample documents through the admin console first, or set `DOCS_DIR`.

---

## 9. Files for this week

| File | Purpose |
| --- | --- |
| [backend/app/agents/week9/agent.py](../../backend/app/agents/week9/agent.py) | The host: ReAct loop, the only Groq call, the trace, the CLI |
| [backend/app/agents/week9/mcp_host.py](../../backend/app/agents/week9/mcp_host.py) | MCP clients: config loading, handshake, `tools/list`, routing `tools/call` |
| [backend/config/mcp_servers.json](../../backend/config/mcp_servers.json) | The only thing that changes when a server is added |
| [backend/mcp_servers/help_centre/server.py](../../backend/mcp_servers/help_centre/server.py) | Server one (ours): `search_help_centre`, `get_article` |
| [backend/mcp_servers/ticket_history/](../../backend/mcp_servers/ticket_history/) | Server two ("Support Ops"): `lookup_ticket`, `get_escalation_history`, `tickets.json` |
| [backend/scripts/week9_capture_wire.py](../../backend/scripts/week9_capture_wire.py) | Raw JSON-RPC capture for wire.json |
| [backend/tests/test_week9_mcp.py](../../backend/tests/test_week9_mcp.py) | 8 tests, no Groq calls |
| [agent_diff.txt](agent_diff.txt), [config_diff.txt](config_diff.txt), [wire.json](wire.json), [tool_counts.md](tool_counts.md), [error_before_after.md](error_before_after.md), [risk_note.md](risk_note.md) | The six Task Set A deliverables |
| [evidence/](evidence/) | Raw traces and the byte-exact wire capture behind them |

---

## 10. Glossary

- **MCP (Model Context Protocol):** an open standard for connecting AI apps to tools and data.
- **Host:** the app that runs the model and decides which servers to trust. Here, `agent.py`.
- **Client:** one MCP connection inside the host, one per server.
- **Server:** a program that offers tools, resources or prompts over MCP. It never runs the model.
- **Tool:** a function the model can choose to call, with a name, a description and an `inputSchema`.
- **Resource:** read-only data identified by a URI that the app can attach to the model's context.
- **JSON-RPC 2.0:** a simple request/response message format: `jsonrpc`, `id`, `method`, `params`, `result`, `error`.
- **Notification:** a JSON-RPC message without an `id`. No reply is expected.
- **stdio transport:** the server runs as a child process and they exchange one JSON message per line on stdin/stdout. So a server must never print anything else to stdout; logs go to stderr.
- **Streamable HTTP:** the transport for remote servers, at a URL such as `http://host:port/mcp`.
- **`isError`:** a flag on a tool result meaning "the tool ran but failed". The message is for the model to read and recover from.
- **FastMCP:** the Python API that turns decorated functions into MCP tools (`mcp.server.fastmcp` in SDK 1.x).
- **Seeded call:** in our runs, a fixed tool call replayed as the agent's first move, so two versions of a tool face exactly the same input.
- **Supply-chain risk:** the risk from running code you didn't write inside your trust boundary.

---

## 11. Key takeaways

1. **Discovery is what makes the config-only addition possible.** The agent has no tool list, so adding server two changed 0 agent lines and 5 config lines, and took the tool count from 2 to 4.
2. **The model runs only in the host.** MCP servers expose capabilities, and the client only forwards the model's choices. Our servers never call Groq, by design.
3. **A tool's docstring is a prompt, and its error message is a prompt too.** Rewriting one tool made the model fix its call instead of giving up, and halved the tokens.
4. **Return failures as `isError` results with an actionable message,** never as an opaque code. The model can only recover from what it can read.
5. **Adding a server extends your trust boundary.** The ticket-history server reaches every customer's PII, logs no caller, and has no auth over HTTP. Don't ship it as-is.
6. **MCP is plumbing, not intelligence.** With new data available, the agent still claimed an action it couldn't take.
