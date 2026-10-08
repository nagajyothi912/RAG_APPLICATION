# Week 7 — Agents vs Fixed Workflows: a Ticket-Reply Agent with Safety Budgets

> **TL;DR.** This week builds two ways to answer an AirFiber support ticket with the same tools, the same model (`openai/gpt-oss-120b` on Groq) and the same reply format. The first is a **ReAct agent**: the model decides which tool to call next, inside a loop guarded by four safety budgets (iterations, tokens, cost, wall-clock time). The second is a **fixed workflow**: plain Python that always runs *retrieve → (maybe escalate) → generate*, with the escalation decision made by an `if` rule. A new third tool, `escalate_ticket`, was added. Both systems ran on the same 10 tickets. In the committed run the fixed workflow passed 10 out of 10 tickets, with a median latency of about 3.8 s and 5,141 tokens. The agent passed 4 out of 10, with a median latency of about 20.4 s and 26,093 tokens. **However, 5 of the agent's 6 failures were Groq HTTP 429 rate-limit errors, not reasoning mistakes**, and the forced budget-termination test also hit a 429, so the budget never fired. The plumbing (loop, budgets, tools, API, UI) is all there. The measurements are noisy and should be re-run before anyone draws strong conclusions from them.

> **Where this guide comes from.** There is **no Week 7 requirement document** in the repo. `docs/assignments/` has only Week 3 and Week 4 task sets. The requirements below are **reconstructed** from code docstrings (`agent.py`, `fixed_workflow.py`, `tools.py`, `tickets.py`, `budget_test.py`, `report.py`), the shape of the committed outputs in `eval/week7/`, the UI, and commit `09bbbe5 "Week-7 changes"`, which is the tip of branch `week-7(Agents)`. Every number below is copied from those files.

---

## 1. The problem in plain words

A customer writes in: *"Third time I am writing about this. The engineer never turned up. Do I get my money back?"* A good reply needs three things:

1. the right **policy text** (the refund rules),
2. a decision on whether this ticket must be **escalated**, meaning handed to a human team with a deadline, and
3. a **well-written reply** that quotes the ticket ID and the correct amount.

You can automate this in two broad ways:

- **Let the LLM drive.** Give the model a toolbox and let it decide, step by step, which tool to use. This is an *agent*. It is flexible, but it can wander, loop or overspend, so it needs hard limits (*budgets*).
- **Hard-code the steps.** Write the order of steps yourself and use a simple rule for the one decision point. This is a *workflow*. It is predictable and cheap, but it only handles the cases you foresaw.

Week 7 asks: **on realistic tickets, does the agent's flexibility actually buy anything over a fixed workflow, and what does it cost?** It also asks you to prove that the agent's safety budgets really stop it.

---

## 2. Requirements (reconstructed)

Legend: ✅ done · ⚠️ done but with a caveat · ❌ not done. All links are relative to `docs/week7/`.

| # | Requirement (reconstructed) | Status | Where |
|---|---|---|---|
| R1 | A ReAct agent: an LLM loop that picks tools through function calling until it gives a final answer | ✅ | [`agent.py`](../../backend/app/services/ticket_reply_app/agent.py) `run_agent()` |
| R2 | Four safety budgets (max iterations = 8, max tokens = 15,000, max cost = $0.10, max wall clock = 60 s) that end the run cleanly, without raising an exception | ✅ | [`agent.py`](../../backend/app/services/ticket_reply_app/agent.py) `BudgetTracker`, `_log_budget_event()` |
| R3 | A fixed workflow with the same tools, model and output contract, and no LLM choosing steps | ✅ (⚠️ at HEAD, see §6) | [`fixed_workflow.py`](../../backend/app/services/ticket_reply_app/fixed_workflow.py) |
| R4 | 10 test tickets: 3 dependent-chain and 7 single-path, used by both systems | ✅ (⚠️ the chain label on T119 is debatable) | [`tickets.py`](../../backend/app/services/ticket_reply_app/tickets.py) |
| R5 | A new **third tool** `escalate_ticket`, with typed/enum parameters and no overlap with the other two tools | ✅ | [`tools.py`](../../backend/app/services/ticket_reply_app/tools.py) |
| R6 | Run both systems and save the per-ticket results | ✅ | [`run_experiment.py`](../../backend/app/services/ticket_reply_app/run_experiment.py) → [`agent_results.json`](../../eval/week7/agent_results.json), [`workflow_results.json`](../../eval/week7/workflow_results.json) |
| R7 | A comparison table with 4 metrics: pass rate, P50 latency, total tokens, cost per ticket | ⚠️ produced, but the agent's numbers are polluted by 429 errors and its token count is measured differently | [`metrics.py`](../../backend/app/services/ticket_reply_app/metrics.py) → [`comparison_table.json`](../../eval/week7/comparison_table.json) |
| R8 | A verdict of 150 words or fewer | ⚠️ 100 words, but it is a template, and some of its sentences contradict the data | [`report.py`](../../backend/app/services/ticket_reply_app/report.py) `build_verdict()` |
| R9 | A forced budget-termination test with a saved log | ⚠️/❌ the script exists, but the only log shows **the budget did NOT fire** (429 error), and the log is git-ignored, so it is not committed | [`budget_test.py`](../../backend/app/services/ticket_reply_app/budget_test.py) → `eval/week7/budget_termination.log` (local only) |
| R10 | `/api/week7/*` endpoints (report, run, budget-test) | ✅ | [`api/week7.py`](../../backend/app/api/week7.py), wired in [`main.py`](../../backend/app/main.py) |
| R11 | A Week 7 UI tab (metric cards, per-ticket table, budget log, tool diff, verdict) | ✅ | [`Week7Page.tsx`](../../frontend/src/components/pages/Week7Page.tsx), [`api.ts`](../../frontend/src/services/api.ts), [`App.tsx`](../../frontend/src/App.tsx) |
| R12 | Automated tests for Week 7 | ❌ none in `backend/tests/` | — |
| R13 | A written analysis / write-up | ❌ none existed before this guide (weeks 5, 6 and 8 have one) | this file |

---

## 3. Concepts covered

**Agent.** A program in which an LLM decides the *next action* itself, such as "call tool X with these arguments" or "I'm done, here is the answer", and repeats until it stops.
*Why:* it can handle situations you did not script. *Where:* `run_agent()` in `agent.py`.

**ReAct (Reason + Act).** A common agent pattern. The model thinks, then **acts** (calls a tool), then **observes** the tool's result, then thinks again, and so on. In code, this is a `while True` loop. Each pass sends the whole conversation so far to the model. *Where:* the `while True:` loop in `agent.py`.

**Tool calling / function calling.** You don't ask the model to write free text such as "now I'll search". Instead, you send it a list of *tools* described as JSON. The model replies with a structured request like `{"name": "retrieve_kb_context", "arguments": "{...}"}`. Your code runs the real function and sends back the result as a `role: "tool"` message. Groq exposes this through the OpenAI-compatible API (`tools=..., tool_choice="auto"`).

**Tool schema.** The JSON description of a tool: its name, a description of when to use it and when **not** to, and its parameters with types and `enum` (allowed values) lists. Good descriptions are how you steer the model. *Where:* `TOOL_SCHEMAS` in `tools.py`.

**Workflow (fixed / hard-coded).** The developer writes the steps. The LLM is only used *inside* one step (writing the reply). It never chooses *which* step comes next. *Where:* `run_fixed_workflow()` in `fixed_workflow.py`.

**Budget.** A hard limit on resources for one ticket. There are four:
| Budget | Default | What it guards against |
|---|---|---|
| `MAX_ITERATIONS` | 8 loop passes | infinite tool-calling loops |
| `MAX_TOKENS` | 15,000 tokens (summed over the agent's own LLM calls) | runaway prompt growth |
| `MAX_COST_USD` | $0.10 | surprise bills |
| `MAX_WALL_CLOCK` | 60 s | a hung or very slow run |

**Termination (clean).** When a budget is used up, the agent stops *on purpose*. It prints a structured `BUDGET_TERMINATED` record, sets `budget_hit` to the name of the budget, and returns whatever reply it has. It does **not** raise an exception. The budgets are checked **at the start of each loop pass**, so a single slow LLM call can still overshoot the wall-clock limit before the next check catches it.

**Dependent chain.** A ticket where a later step depends on the result of an earlier step. For example: look up the policy, then decide to escalate, then write a reply that includes the escalation note. These are the tickets where an agent's step-by-step reasoning could in theory help. The tickets marked `chain=True` are T010, T017 and T119.

**Single-path ticket.** A simple question answered by *retrieve → generate* with no branching (for example, "what does an orange light mean?").

**Escalation.** Handing the ticket to a named human team with an **SLA**, a promised response time. For example, `priority_customer` goes to the "Priority Support Lead" with an SLA of 2 hours.

**Latency / P50.** Latency is the wall-clock time from start to finish for one ticket. **P50** is the *median*: sort the 10 latencies, and P50 is the middle value. Half the tickets were faster and half were slower. It is less distorted by one outlier than the average is.

**Token / token cost.** Tokens are the word-pieces the model reads and writes. Cost is calculated as `prompt_tokens × input price + completion_tokens × output price`. The code uses $0.09 per 1M tokens for both input and output (constant in `agent.py`, comment cites Groq pricing).

**Pass rate.** The fraction of tickets whose reply passes every *applicable* deterministic check, listed in the ticket's `assertions` field. The checks are in `metrics.py`:
- `ticket_id_echoed`: the reply mentions the ticket ID (e.g. `T017`).
- `refund_amount_numeric`: if the reply promises a refund, it states an amount in ₹.
- `priority_escalation`: replies to Priority-tier tickets contain a word such as "priority", "escalat" or "senior".
- `no_refund_outside_30_days`: a customer with more than 30 days of tenure who asks for a refund is not promised a "100% refund" or "full refund of".

**HTTP 429.** "Too Many Requests". Groq refused the call because the account's tokens-per-minute limit was reached. This one detail shapes most of this week's results.

---

## 4. What was implemented

### 4.1 The pieces

| Piece | What it does |
|---|---|
| `tools.py` | Holds the three tool schemas and implementations, a mock CRM (`ACCOUNT_DB`), escalation routing (`ESCALATION_TEAMS`), and `dispatch_tool()`, which maps a tool name to the Python function. Both systems call tools only through `dispatch_tool`. |
| `retrieve_kb_context` | **No LLM call and no FAISS search.** It returns the ticket's hand-written `context` string (passed in as `_context_override`). The docstring explains why: this keeps the two systems' inputs identical, and neither needs a live backend. So Week 7 does **not** exercise the Week 3/4 retriever. |
| `generate_ticket_reply` | One Groq call (`temperature=0`, `max_tokens=300`). The system prompt requires: start with `[Ticket #ID]`, add a `[Priority Escalation: <team>]` tag when escalated, use only the given context, cite the source, stay under 120 words, and say "I don't know based on the provided documents." if the context doesn't cover the question. |
| `escalate_ticket` *(new in Week 7)* | **No LLM call.** It looks up the team and SLA for the `reason` and returns an `escalation_note` such as `"[Priority Escalation: Field Service Supervisor] Ticket T017 escalated — reason: missing_order, severity: high."`. `reason` is an enum of 5 values (`missing_order`, `repeated_contact`, `priority_customer`, `unresolved_technical`, `refund_dispute`). `severity` is an enum of 4 values (`low`/`medium`/`high`/`critical`). |
| `agent.py` | `BudgetTracker` (4 budgets) and `run_agent()` (the ReAct loop, `tool_choice="auto"`, `temperature=0`, `max_tokens=512` per step). |
| `fixed_workflow.py` | `_should_escalate()` (a rule with no LLM), `_severity()`, and `run_fixed_workflow()`. |
| `tickets.py` | 10 tickets. Each has tier, tenure, refund flag, `chain` flag, question, `context` (the "KB passage"), `expected_tools` and `assertions`. The docstring says they are drawn from the Week 6 pool `eval/week6/eval_set_25.jsonl`. |
| `metrics.py` | The 4 assertions, `passed()`, `p50()`, token and cost sums, and `build_comparison_table()`. |
| `run_experiment.py` | Runs the agent on all 10 tickets (with a fresh budget per ticket), then the workflow on all 10, then writes 3 JSON files. |
| `budget_test.py` | Runs the agent on T010 with `max_iterations=2` (and `max_tokens=6000`) to force the iteration budget to fire, then writes `budget_termination.log`. |
| `report.py` | Reads the JSON files. `build_verdict()` (100-word template), `build_tool_diff()` (third-tool description for the UI), `get_week7_report()` (used by the API) and `print_report()` (CLI). |
| `api/week7.py` | `GET /api/week7/report`, `POST /api/week7/run` (background task), `POST /api/week7/budget-test` (background task). |
| `Week7Page.tsx` | The "Week 7" tab. It has buttons for Run Experiment, Budget Test and Refresh. It shows 4 metric cards, then three sub-tabs: **Comparison Table** (per-ticket rows with a click-to-expand detail and the verdict), **⚡ Budget Log**, and **Third Tool Diff**. |

> **Output path note.** The docstrings in `run_experiment.py` and `budget_test.py` say output goes to `backend/eval/week7/`. In fact the variable named `BACKEND` is `Path(__file__).parents[4]`, which is the **repo root**, so files land in the top-level **`eval/week7/`**. The `report.py` and API code read from the same place.

### 4.2 The agent loop (ReAct)

```text
ticket ─► messages = [system prompt, "Ticket ID / tier / question"]
              │
              ▼
   ┌──────────────────────────────────────────────┐
   │ budget.check()  ── any of the 4 exhausted? ──┼──yes──► log BUDGET_TERMINATED,
   │      │ no                                    │         budget_hit = <name>, stop
   │      ▼                                       │
   │ iterations += 1                              │
   │ Groq chat.completions(messages, tools=3,     │
   │                       tool_choice="auto")    │──error (e.g. 429)──► reply = "[Agent error…]", stop
   │      │                                       │
   │ add prompt+completion tokens & cost          │
   │      │                                       │
   │ tool_calls in reply?                         │
   │   no ──► reply = model's text, STOP (done)   │
   │   yes ─► for each call: dispatch_tool()      │
   │          append {"role":"tool", result}      │
   │          (generate_ticket_reply → reply)     │
   └──────────────◄───────────────────────────────┘ loop
```

A typical successful run in the data takes 3 iterations: (1) call `retrieve_kb_context`, (2) call `generate_ticket_reply`, (3) the model returns plain text and the loop ends. That plain text becomes the final `reply`, replacing the tool's draft. In the saved runs it is essentially the same reply repeated by the model.

### 4.3 The fixed workflow

```text
ticket
  │
  ▼
Step 1  retrieve_kb_context(query=question, product_area="any", top_k=3)     ← always
  │
  ▼
Step 2  _should_escalate(ticket)   (pure Python, first match wins)
          status=="unactivated" or missed_install ≥ 2   → missing_order
          relocation_days_pending ≥ 14                  → missing_order
          tier=="Priority" and refund_requested         → priority_customer
          question has "third time"/"again"/
            "nobody called"/"every week"                → repeated_contact
          otherwise                                     → no escalation
        if reason: escalate_ticket(reason, severity)  (missing_order/priority → high, else medium)
  │
  ▼
Step 3  generate_ticket_reply(context, escalation_note,
                              tone = "apologetic" if escalated else "informational")  ← always
  │
  ▼
same result shape as the agent (reply, tools_called, tokens, cost, latency, budget_hit=None)
```

There is exactly one LLM call per ticket, made inside step 3. There is no loop and there are no budgets, because nothing can run away.

---

## 5. Analysis & results

All numbers come from [`eval/week7/comparison_table.json`](../../eval/week7/comparison_table.json) (files dated 2026-09-28, committed in `09bbbe5`). Model: `openai/gpt-oss-120b`. Default budgets for every agent run: 8 iterations / 15,000 tokens / $0.10 / 60 s.

### 5.1 Headline comparison table

| Metric (10 tickets each) | Agent | Fixed workflow |
|---|---|---|
| Pass rate | **40%** (4/10) | **100%** (10/10) |
| P50 latency | 20,378.9 ms (~20.4 s) | 3,794.5 ms (~3.8 s) |
| Total tokens (all 10) | 26,093 | 5,141 |
| Cost per ticket (USD) | $0.000235 | $0.000046 |

### 5.2 Per ticket

| Ticket | Type | Agent: pass / tools / tokens / ms | Workflow: pass / tools / tokens / ms |
|---|---|---|---|
| T010 | chain, Priority | ❌ — none — 0 — 7,285 **(429 on 1st call)** | ✅ retrieve→escalate(missing_order)→generate — 623 — 3,104 |
| T017 | chain, Priority | ❌ retrieve — 1,134 — 29,316 **(429)** | ✅ retrieve→escalate(missing_order)→generate — 585 — 5,225 |
| T119 | chain | ✅ retrieve→generate — 4,088 — 39,722 | ✅ retrieve→generate — 535 — 3,040 |
| T001 | single | ❌ retrieve — 1,075 — 18,031 **(429)** | ✅ retrieve→generate — 459 — 3,861 |
| T003 | single | ❌ retrieve→generate — 2,346 — 20,041 **(429 after a good draft)** | ✅ retrieve→generate — 434 — 3,728 |
| T016 | single | ✅ retrieve→generate — 3,658 — 41,240 | ✅ retrieve→generate — 418 — 2,769 |
| T022 | single | ❌ retrieve→generate — 2,482 — 43,391 **(429 after a good draft)** | ✅ retrieve→generate — 542 — 4,034 |
| T073 | single | ✅ retrieve→generate — 3,747 — 13,290 | ✅ retrieve→generate — 471 — 2,974 |
| T118 | single, Priority | ❌ retrieve→generate — 3,907 — 19,434 **(real miss: never escalated, so the reply lacks a priority marker)** | ✅ retrieve→escalate(priority_customer)→generate — 606 — 4,305 |
| T007 | single | ✅ retrieve→generate — 3,656 — 20,717 | ✅ retrieve→generate — 468 — 5,356 |

No budget fired in the main run (`budget_hit` is `null` for all 20 rows). The slowest agent ticket took 43.4 s, under the 60 s limit.

### 5.3 What the numbers really mean (read this before quoting them)

1. **Most agent failures are infrastructure failures, not reasoning failures.** 5 of the 6 failed agent tickets (T010, T017, T001, T003, T022) have a reply of `"[Agent error: LLM call failed — Error code: 429 - … Rate limit reached for model openai/gpt-oss-120b … tokens per minute (TPM)…"]`. The Week 7 version of the loop had **no retry**: any exception ended the run. In T003 and T022 the agent had *already* produced a good draft through `generate_ticket_reply`, but the *next* call (to say "done") hit a 429 and overwrote the reply with the error text. On the 5 tickets that did not hit a 429, the agent passed 4 of 5. The single genuine miss is T118.
2. **The agent called `escalate_ticket` 0 times in 10 runs. The workflow called it 3 times (T010, T017, T118).** For T010 and T017 the agent never got far enough to decide, because of the 429s. For T118, a Priority-tier customer asking for a refund outside the 30-day window, it reached a reply without escalating, and so failed the `priority_escalation` check. Notably, the `fixed_workflow.py` docstring itself argues that a human might say T118 does *not* need escalation, because only a credit applies. The ticket's `expected_tools` and `assertions` nevertheless require escalation, so the grading rewards the rule.
3. **The token comparison is not like-for-like.** The agent's `total_tokens` counts only the agent's *own* decision calls, and each one resends the growing conversation. That is why a 3-iteration ticket costs about 3,600–4,100 tokens. It does **not** include the tokens used inside `generate_ticket_reply`, roughly 400–570 per draft according to `tool_results`. The workflow's count is *only* that `generate_ticket_reply` call. So the real gap is a little *larger* than 26,093 vs 5,141. The direction (agent uses about 5× or more tokens) is robust.
4. **Latency.** The agent makes 2–3 sequential LLM calls where the workflow makes 1, so a slower agent is expected. But its ~20 s P50 is also inflated by slow or failed calls under rate limiting. Treat "about 5× slower" as indicative, not exact.
5. **Cost is tiny either way.** $0.000235 vs $0.000046 per ticket. Both are nowhere near the $0.10 budget. The relative gap (about 5×) matters at scale, not per ticket.

### 5.4 The generated verdict (word for word, 100 words)

`report.build_verdict()` produces this text from the JSON files. It is what the UI shows:

> The execution path varies for Priority-tier and multi-step dependent tickets (T010, T017, T118, T119). In those cases the agent conditionally invokes escalate_ticket based on LLM reasoning (0/10 agent runs), while the fixed workflow applies a deterministic rule (3/10 workflow runs). Agent pass rate: 40% vs workflow: 100%. Agent P50 latency: 20379 ms vs workflow: 3794 ms. Agent total tokens: 26093 vs workflow: 5141. For simple informational tickets (T001, T003, T007, T016, T022, T073) both paths produce identical tool sequences and equivalent replies — the fixed workflow is sufficient there. For dependent-chain tickets, the agent's dynamic branching is the observed differentiator.

**Caveat.** Only the numbers in this verdict are filled in from data. The sentences are fixed text. With these results, two claims are **not supported**:
- "both paths produce identical tool sequences and equivalent replies" is false for T001, T003 and T022, where the agent's replies are 429 error strings.
- "the agent's dynamic branching is the observed differentiator" is not supported either: the agent branched (escalated) zero times.

A fairer one-line reading of *this* run: **the fixed workflow matched or beat the agent on every metric, and the experiment did not show the agent adding value on the dependent-chain tickets.**

### 5.5 When to use an agent vs a workflow (grounded in this experiment)

| Use a **fixed workflow** when… | Consider an **agent** when… |
|---|---|
| The steps are known ahead of time. Here, *every* ticket is retrieve → (escalate?) → generate. | The number and order of steps truly can't be known in advance (open-ended investigation, many tools, unknown depth). |
| The one decision can be written as a rule. `_should_escalate()` is about 15 lines and got 10/10. | The decision needs judgment that a rule can't capture, and you can *measure* that the agent's judgment is better. |
| You care about latency, cost and reliability. The workflow made 1 LLM call per ticket, so there were fewer chances to hit a 429, and it was about 5× faster and cheaper. | You can afford several LLM calls per task, plus retries, budgets and monitoring. |
| You need auditability: the same input always takes the same path. | You accept that the path varies, and you trace and evaluate it (Week 8 builds trajectory evals for exactly this). |

The lesson from Week 7: **start with a workflow. Move to an agent only for the part of the problem where you have evidence that fixed rules fail.** Every extra LLM call in the loop is another chance for latency, cost and failures (here, rate limits). Budgets limit the damage, but they don't remove it.

### 5.6 The forced budget-termination test

`budget_test.py` runs the agent on **T010** with `max_iterations=2`. The goal: the loop does 2 passes, then at the start of pass 3 `budget.check()` returns `"max_iterations"`, and the agent stops cleanly before finishing its tools.

**What actually happened.** The file `eval/week7/budget_termination.log` **exists on disk** (run at `2026-09-28T14:29:37Z`), but:
- it is **not committed**. `.gitignore` line 23 (`*.log`) ignores it, so a fresh clone won't have it, and the UI's "Budget Log" tab will show "No budget termination log yet".
- its contents show that **the budget did not fire**:

```json
"budget_hit": null,
"iterations_completed": 2,
"total_tokens": 1237,
"tools_called_before_termination": ["retrieve_kb_context"],
"partial_reply": "[Agent error: LLM call failed — Error code: 429 - … Rate limit reached …",
"clean_termination": false,
"verdict": "Budget did NOT fire as expected — check configuration."
```

The 2nd LLM call hit a 429, so the loop ended through the error path before it could reach the 3rd budget check. **The "forced budget termination" deliverable is therefore not demonstrated by any saved artifact.** The code path (`BudgetTracker.check()` → `_log_budget_event()` → `budget_hit` set) is simple and looks correct, but no run has captured it firing.

---

## 6. What is NOT implemented / limitations / known gaps

- **No Week 7 tests.** `backend/tests/` has no file that imports `ticket_reply_app` or hits `/api/week7`. Unit tests could cover `BudgetTracker.check()`, `_should_escalate()` and the assertions without calling Groq.
- **Budget termination not shown to work** (§5.6). The log shows a 429 instead, and the log is git-ignored.
- **Rate-limit errors dominate the agent's results.** The Week 7 loop had no retry. The current code (HEAD, Week 8 branch) adds a 4-attempt retry with back-off on 429 in `run_agent`, but the committed Week 7 numbers were **not re-run** with it.
- **Asymmetric token accounting** (§5.3 point 3): the agent's tokens exclude the `generate_ticket_reply` call, and the workflow's include only that call.
- **The verdict is a template.** Its prose contradicts the current data (§5.4).
- **"Retrieval" is mocked.** `retrieve_kb_context` returns each ticket's hand-written `context`, so the Week 3/4 FAISS/BM25 retriever isn't exercised. Both systems always get perfect context.
- **The budgets check between iterations only.** One long LLM call can run past the wall-clock limit before the next check.
- **Schema enums are not validated locally.** The `tools.py` docstring says out-of-range values cause "a schema validation error", but `dispatch_tool()` doesn't check enums. It relies on the model and the API following the schema.
- **`expected_tools` is not graded in Week 7.** Each ticket lists the tools it should use, but pass/fail is only the text assertions. Scoring the tool path itself is what Week 8's `trajectory_eval.py` adds.
- **Weak chain labelling.** T119 is marked `chain=True`, but its `expected_tools` is just retrieve → generate, the same as the single-path tickets.
- **Small sample, one run.** 10 tickets, a single run per system, and no repeated trials, so there are no confidence intervals.
- **UI polling quirk.** After "Run Experiment", the page polls `/api/week7/report` and stops as soon as `available` is true. If old results already exist, it stops right away and keeps showing them until you click Refresh.
- **Docstring path mismatch.** The scripts say `backend/eval/week7/`, but the real output path is the top-level `eval/week7/` (§4.1).
- **`lookup_order_record` is NOT part of Week 7.** `git show 09bbbe5:backend/app/services/ticket_reply_app/tools.py` has only three tools. `lookup_order_record`, `ORDERS_DB`, `TOOL_SCHEMAS_BASELINE`/`TOOL_SCHEMAS_MITIGATED`, the "mitigated" prompt and the input sanitiser were added in commit **`7609dde`** (2026-10-06, the Week 8 commit, despite its "week4" message). **Side effect:** at HEAD, `TOOL_SCHEMAS` (used by the baseline agent) has **4** tools, while `fixed_workflow.py` still uses 3. Re-running `run_experiment.py` on the current branch therefore breaks the "same tools" condition of the Week 7 comparison. To reproduce Week 7 exactly, check out branch `week-7(Agents)` (= `09bbbe5`).

---

## 7. How to run & verify

> ⚠️ `run_experiment` and `budget_test` (and the matching UI buttons and POST endpoints) make **real Groq calls**. They need `GROQ_API_KEY` in `backend/.env`, use your token quota, and can hit 429 rate limits, which is exactly what happened in the committed run. They also **overwrite** the files in `eval/week7/`.

```bash
# 0. Exact Week 7 code (3 tools, no retry). Skip to stay on the current branch.
git checkout "week-7(Agents)"

# 1. Backend setup (from backend/)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install torch && pip install -r requirements.txt
cp .env.example .env            # set GROQ_API_KEY; GROQ_MODEL defaults to openai/gpt-oss-120b

# 2. Read the committed results — NO Groq call, just reads eval/week7/*.json
python -m app.services.ticket_reply_app.report

# 3. Re-run the agent-vs-workflow experiment (calls Groq; ~20 agent+workflow runs)
python -m app.services.ticket_reply_app.run_experiment

# 4. Forced budget termination on T010 with max_iterations=2 (calls Groq)
python -m app.services.ticket_reply_app.budget_test
cat ../eval/week7/budget_termination.log   # look for "budget_hit": "max_iterations", "clean_termination": true

# 5. API + UI
uvicorn app.main:app --reload --port 8000
curl -s http://127.0.0.1:8000/api/week7/report | python -m json.tool | head -40   # no Groq
# curl -X POST http://127.0.0.1:8000/api/week7/run           # background run, calls Groq
# curl -X POST http://127.0.0.1:8000/api/week7/budget-test   # background run, calls Groq

cd ../frontend && npm install && npm run dev   # open http://localhost:5173/#week7
```

**What to check:**
- The `report` output matches §5.1.
- In a fresh `budget_termination.log`, `budget_hit` is `"max_iterations"` and `clean_termination` is `true`. If you see a 429 again, wait a minute and retry. On HEAD the loop retries 429s itself.
- On re-runs, look at the `reply` field in `agent_results.json`. Any `"[Agent error: …"` means that ticket's result says nothing about agent quality.

---

## 8. Files for this week

| File | Role | Added in |
|---|---|---|
| [`backend/app/services/ticket_reply_app/agent.py`](../../backend/app/services/ticket_reply_app/agent.py) | ReAct loop, `BudgetTracker`, system prompt | `09bbbe5` (modified in `7609dde` for Week 8) |
| [`backend/app/services/ticket_reply_app/fixed_workflow.py`](../../backend/app/services/ticket_reply_app/fixed_workflow.py) | Hard-coded 3-step workflow and escalation rule | `09bbbe5` |
| [`backend/app/services/ticket_reply_app/tools.py`](../../backend/app/services/ticket_reply_app/tools.py) | 3 tool schemas and implementations, mock CRM, dispatcher | `09bbbe5` (`lookup_order_record` etc. added in `7609dde`) |
| [`backend/app/services/ticket_reply_app/tickets.py`](../../backend/app/services/ticket_reply_app/tickets.py) | The 10 test tickets | `09bbbe5` |
| [`backend/app/services/ticket_reply_app/metrics.py`](../../backend/app/services/ticket_reply_app/metrics.py) | Assertions, P50, tokens, cost, comparison table | `09bbbe5` |
| [`backend/app/services/ticket_reply_app/run_experiment.py`](../../backend/app/services/ticket_reply_app/run_experiment.py) | Runs both systems and writes the JSON files | `09bbbe5` |
| [`backend/app/services/ticket_reply_app/budget_test.py`](../../backend/app/services/ticket_reply_app/budget_test.py) | Forced budget termination test | `09bbbe5` |
| [`backend/app/services/ticket_reply_app/report.py`](../../backend/app/services/ticket_reply_app/report.py) | Verdict, tool diff, CLI report, API payload | `09bbbe5` |
| [`backend/app/api/week7.py`](../../backend/app/api/week7.py) | `/api/week7/report`, `/run`, `/budget-test` | `09bbbe5` |
| [`backend/app/main.py`](../../backend/app/main.py) | Registers `week7_router` under `/api` | `09bbbe5` (+2 lines) |
| [`eval/week7/agent_results.json`](../../eval/week7/agent_results.json) | 10 full agent runs (messages, tool calls, replies) | `09bbbe5` |
| [`eval/week7/workflow_results.json`](../../eval/week7/workflow_results.json) | 10 full workflow runs | `09bbbe5` |
| [`eval/week7/comparison_table.json`](../../eval/week7/comparison_table.json) | Headline metrics and 20 per-ticket rows | `09bbbe5` |
| `eval/week7/budget_termination.log` | Budget test output (local only, git-ignored; shows a 429, not a budget hit) | not committed |
| [`frontend/src/components/pages/Week7Page.tsx`](../../frontend/src/components/pages/Week7Page.tsx) | Week 7 tab UI | `09bbbe5` |
| [`frontend/src/services/api.ts`](../../frontend/src/services/api.ts) | `getWeek7Report`, `triggerWeek7Experiment`, `triggerBudgetTest` | `09bbbe5` |
| [`frontend/src/App.tsx`](../../frontend/src/App.tsx), [`frontend/src/index.css`](../../frontend/src/index.css) | Tab routing (`#week7`), `w7-*` styles | `09bbbe5` |

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **Agent** | An LLM in a loop that chooses its own next action (a tool call or a final answer). |
| **ReAct** | "Reason + Act": think → call a tool → read the result → repeat. |
| **Tool / function calling** | The model returns a structured request to run a named function with JSON arguments, instead of free text. |
| **Tool schema** | The JSON description (name, description, typed parameters, enums) that tells the model what a tool does and when to use it. |
| **Enum** | A fixed list of allowed values for a parameter (e.g. `severity ∈ {low, medium, high, critical}`). |
| **Workflow** | Steps hard-coded by a developer. The LLM is used inside a step, never to pick steps. |
| **Budget** | A hard per-ticket limit on iterations, tokens, cost or time. |
| **Clean termination** | Stopping on purpose when a budget is reached, with a logged record and no exception. |
| **Dependent chain** | A ticket where a later step needs the result of an earlier one (policy → escalate → reply). |
| **Single-path** | A ticket solved by retrieve → generate with no branching. |
| **Escalation / SLA** | Handing a ticket to a human team / that team's promised response time. |
| **Latency** | Time from start to finish for one ticket. |
| **P50 (median)** | The middle value of the sorted latencies. Half are faster, half slower. |
| **Token** | A word-piece. LLM usage and price are counted in tokens. |
| **Prompt / completion tokens** | Tokens sent to the model / tokens the model writes back. |
| **Pass rate** | Share of tickets whose reply passes all of its deterministic assertions. |
| **Assertion** | A deterministic code check on the reply text (e.g. "mentions the ticket ID"). |
| **HTTP 429** | "Too Many Requests": the provider's rate limit was hit. |
| **Groq** | The hosted LLM provider used for every call (OpenAI-compatible API). |
| **Mock CRM** | `ACCOUNT_DB` in `tools.py`, a hard-coded dict standing in for a real customer database. |

---

## 10. Key takeaways

- Week 7 builds a **ReAct agent with four working budget checks** and a **hard-coded workflow** over the same three tools (`retrieve_kb_context`, `escalate_ticket` *(new)*, `generate_ticket_reply`), the same model and the same reply format.
- On the committed run, the **workflow won on every metric**: 100% vs 40% pass, about 3.8 s vs about 20.4 s P50, 5,141 vs 26,093 tokens, and $0.000046 vs $0.000235 per ticket.
- **5 of the agent's 6 failures were Groq 429 rate-limit errors**, not wrong answers. The only genuine agent miss was T118, where it did not escalate a Priority ticket. The agent escalated 0 times; the workflow escalated 3 times.
- The **forced budget-termination test has not been demonstrated**. Its only log shows a 429 and `budget_hit: null`, and that log is git-ignored.
- Agents cost more by design: every loop pass resends the whole conversation, so tokens and latency grow with each step, and every extra call is another chance to fail.
- **Default to a workflow** when the steps are known and the decision fits in a rule. Use an agent only where you can *show* that rules fail, and then add budgets, retries and trajectory evaluation (Week 8).
- `lookup_order_record` (and the "mitigated" prompts) are **Week 8 additions** (`7609dde`), not Week 7. Re-running the experiment at HEAD gives the agent 4 tools, while the workflow still uses 3.
