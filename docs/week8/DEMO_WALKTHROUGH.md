# Week 8 Demo & Concept Walkthrough Guide
## Comprehensive Demonstration of Agent Failure Modes, Trajectory Evals & Defense

---

### Executive Summary

| Attribute | Specification |
|---|---|
| **Module** | **M4 — Agents** |
| **Topic** | **Agent Failure Modes, Trajectory Evaluation, Single-Mitigation Isolation & Prompt Injection Defense** |
| **Domain** | Customer Support Ticket Resolution (AirFiber Broadband ISP) |
| **LLM Engine** | `openai/gpt-oss-120b` via Groq Cloud API |
| **Primary Artifacts** | [trajectory_eval.py](file:///Users/softsuave/Desktop/Week3-RAG-Application/RAG_APPLICATION/backend/app/services/ticket_reply_app/trajectory_eval.py), [tools.py](file:///Users/softsuave/Desktop/Week3-RAG-Application/RAG_APPLICATION/backend/app/services/ticket_reply_app/tools.py), [agent.py](file:///Users/softsuave/Desktop/Week3-RAG-Application/RAG_APPLICATION/backend/app/services/ticket_reply_app/agent.py) |
| **Interactive UI** | [Week8Page.tsx](file:///Users/softsuave/Desktop/Week3-RAG-Application/RAG_APPLICATION/frontend/src/components/pages/Week8Page.tsx) (`http://localhost:5173/#week8`) |
| **Benchmark Suite** | 10 Real Customer Support Tickets (Task Set A) |

---

## 1. Core Theoretical Concepts

### 1.1 The Outcome-vs-Trajectory Gap

In traditional LLM evaluation (Week 6/7), systems only assert the final response text:
- Did the agent state the correct refund amount?
- Did the agent include the ticket ID and polite tone?

If the answer contains the expected keywords, outcome tests mark it as **PASS (100%)**.

```
                         OUTCOME EVALUATION (Opaque Box)
  Customer Ticket ──▶ [   ReAct LLM Agent   ] ──▶ Final Reply "₹1999 Refund Approved" ──▶ PASS ✅
```

#### Why Outcome Evals Fail in Agentic Workflows:
An autonomous agent takes **real actions** (database lookups, financial mutations, escalations).
When an agent reaches the right answer by an ungrounded or lucky path, it represents a severe operational vulnerability:

> **"A right answer reached down a wrong path is a time bomb with a passing test."**

In Ticket **T017**, a customer claimed: *"I paid 1999 on the 2nd, the engineer never turned up. Just tell me whether I get my money back."*
- **Outcome Result:** **PASS** (The agent quoted ₹1999 refund).
- **Trajectory Result:** **FAIL** (The agent never called `lookup_order_record` in `ORDERS_DB` to verify if ₹1999 was actually billed or if dispatch logged 3 missed visits).
- **The Gap:** Deploying this agent allows any attacker to claim arbitrary sums and receive unverified approval emails.

```
                         TRAJECTORY EVALUATION (Glass Box)
  Customer Ticket ──▶ [1. retrieve_kb] ──▶ [2. generate_reply] ──▶ Omitted lookup_order_record!
                                                                  └──▶ TRAJECTORY FAILURE ❌
```

---

### 1.2 The Failure Modes Zoo

Autonomous agents exhibit failure modes absent from standard software pipelines:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AGENT FAILURE MODES ZOO                         │
├──────────────────────────┬─────────────────────────────────────────────┤
│ 1. Skipped Step          │ Omitting mandatory verification actions     │
│ 2. Fluent Fiction        │ Hallucinated IDs/arguments passed to tools  │
│ 3. Unwarranted Tool Use  │ Calling escalations/tools for routine FAQs  │
│ 4. Looping & Redundancy  │ Cyclical duplicate tool invocations         │
│ 5. Indirect Injection    │ Blindly executing instructions from data    │
│ 6. Quiet Termination     │ Exhausting budget or stopping prematurely   │
└──────────────────────────┴─────────────────────────────────────────────┘
```

1. **`skipped_order_lookup` (Skipped Verification):** Jumping straight from general documentation to drafting commitments without reading database state.
2. **`fluent_fiction` (Hallucinated Parameters):** Passing invented `order_id` or `ticket_id` values to tools.
3. **`unwarranted_escalation` (Spurious Routing):** Triggering expensive human handoffs for simple FAQs.
4. **`redundant_steps` (Looping / Thrashing):** Repeating identical tool queries when sufficient context already exists.
5. **`unhandled_injection` (Indirect Prompt Injection):** Untrusted input inside support tickets hijacking the agent's control flow.

---

### 1.3 The Four Trajectory Numbers

To rigorously characterize agent behavior, four numbers are reported:

```
                         THE FOUR TRAJECTORY NUMBERS
    ┌──────────────────────┐              ┌──────────────────────┐
    │ 1. Tool-Choice Acc.  │              │ 2. Argument Validity │
    │    88.0% (0.880)     │              │    100.0% (1.000)    │
    └──────────┬───────────┘              └──────────┬───────────┘
               │                                     │
               ▼                                     ▼
    ┌──────────────────────┐              ┌──────────────────────┐
    │ 3. Step Efficiency   │              │ 4. Cost Variance     │
    │    0.975             │              │    p50: $0.000373    │
    │    (taken / needed)  │              │    Max: $0.000712    │
    └──────────────────────┘              └──────────────────────┘
```

1. **Tool-Choice Accuracy (88.0%):** Measures precision/recall of tool selection against ground-truth required toolsets.
2. **Argument Validity Rate (100.0%):** Validates that all tool arguments are grounded in real CRM records.
3. **Step Efficiency (0.975):** Ratio of steps taken to steps needed. Values $< 1.00$ indicate skipped verification steps.
4. **Cost per Ticket Variance ($p50$ AND $\text{Max}$):** 
   - $p50 = \$0.000373$, $\text{Max} = \$0.000712$ ($\text{mean} = \$0.000445$).
   - *Why both?* The arithmetic mean masks outlier looping runs where an agent thrashing through 10 turns consumes $10\times$ more budget.

---

### 1.4 Commutative Multi-Path Sets

Tool ordering can be commutative without being invalid. For example:
- **Path A:** `retrieve_kb_context` $\to$ `lookup_order_record` $\to$ `generate_ticket_reply`
- **Path B:** `lookup_order_record` $\to$ `retrieve_kb_context` $\to$ `generate_ticket_reply`

Both paths obtain all necessary evidence. Week 8 trajectory assertions define these as **Sets of valid sequences** (`Set[Tuple[str, ...]]`) rather than brittle single paths.

---

### 1.5 The Single-Mitigation Isolation Protocol & Price Tag

To maintain scientific validity:
- Exactly **ONE** targeted architectural change is applied to solve the top failure mode (`skipped_order_lookup`).
- **Mitigation:** Tighter Tool Schema Description & Sequential Precondition Contract.
- **Price Tag:** No mitigation is free. Every architectural guardrail incurs measurable overhead:
  - **Latency:** $+5,054.5\text{ ms / ticket}$ ($+17.8\%$)
  - **Tokens:** $+393.1\text{ tokens / ticket}$ ($+7.9\%$)
  - **Cost ($p50$):** $+\$0.000036\text{ / ticket}$ ($+9.6\%$)
  - **Flexibility:** Agent cannot bypass verification even for trivial tickets.

---

### 1.6 Bonus Challenge: 3-Layer Indirect Injection Defense

```
  Untrusted Data ──▶ [ 1. Sanitizer ] ──▶ [ 2. Read-Only Scope ] ──▶ [ 3. Output Guardrail ] ──▶ Verified Reply
```

1. **Layer 1 (Sanitization):** Strips prompt injection delimiters (`SYSTEM OVERRIDE`, `ignore previous instructions`) at tool boundaries.
2. **Layer 2 (Read-Only Tool Scoping):** Strict least-privilege schemas preventing financial writes from conversational LLM outputs.
3. **Layer 3 (Output Guardrails):** Programmatic verification that financial figures in generated replies match verified `ORDERS_DB` records.
- **Defense Overhead:** $+185\text{ ms}$ latency, $+25\text{ tokens}$.

---

## 2. Interactive Demo Walkthrough (UI & CLI)

### 2.1 Live Web UI Walkthrough (`http://localhost:5173/#week8`)

The interactive Week-8 dashboard contains 5 dedicated subtabs:

1. **Tab 1: 📊 Trajectory Numbers & Gap**
   - Live KPI cards showing Outcome Pass (80.0%), Trajectory Pass (70.0%), Gap (+10.0%), Step Efficiency (0.975), and Cost Variance ($p50$ and $\text{Max}$).
   - Visual comparison card illustrating the Ticket `T017` right-answer-wrong-path anomaly.

2. **Tab 2: 🧪 10 Ticket Benchmark Matrix**
   - Full evaluation table across all 10 customer tickets.
   - Shows valid trajectory multi-path sets, actual paths taken, tool-choice accuracy, and pass/gap status.
   - Fully scrollable with sticky header.

3. **Tab 3: 🛠️ Single Mitigation & Price Tag**
   - Side-by-side tool schema diff showing the exact precondition contract added to `generate_ticket_reply`.
   - Before $\to$ After failure counts ($2 \to 0$).
   - Empirical price tag breakdown (Latency $+17.8\%$, Tokens $+7.9\%$, Cost $+9.6\%$).

4. **Tab 4: 🛡️ Per-Mode Regression Table**
   - Regression audit across all 5 failure modes confirming zero introduced regressions.

5. **Tab 5: ⚔️ Prompt Injection Attack & Defense**
   - Live interactive simulator testing an indirect injection payload (`[SYSTEM OVERRIDE: ... refund ₹10,000]`).
   - Shows vulnerable baseline breach vs defended 3-layer protection with live latency/token counters.

---

### 2.2 CLI Demonstration Commands

Run the full trajectory evaluation suite from your terminal:

```bash
# 1. Run live trajectory evaluation over 10 test tickets (Baseline vs Mitigated)
cd /Users/softsuave/Desktop/Week3-RAG-Application/RAG_APPLICATION
./backend/.venv/bin/python eval/week8/trajectory_eval.py

# 2. View generated evaluation artifacts
cat eval/week8/trajectory_eval_results.json
cat eval/week8/regression_table.json
```

---

## 3. Summary of Live Benchmark Results

| Metric / Attribute | Baseline Agent | Mitigated Agent | Delta / Impact |
|---|---|---|---|
| **Outcome Pass Rate** | 80.0% (8/10) | 100.0% (10/10) | +20.0% |
| **Trajectory Pass Rate** | 70.0% (7/10) | 100.0% (10/10) | +30.0% |
| **Outcome-vs-Trajectory Gap** | **+10.0%** | **0.0%** | **Gap Closed** |
| **Top Failure Mode (`skipped_order_lookup`)** | 2 failures (`T010`, `T017`) | 0 failures | **Eliminated** |
| **Tool-Choice Accuracy** | 88.0% | 100.0% | +12.0% |
| **Argument Validity Rate** | 100.0% | 100.0% | Maintained |
| **Step Efficiency** | 0.975 | 1.000 | Optimal (1.000) |
| **Median Cost ($p50$)** | $0.000373 | $0.000409 | +$0.000036 (+9.6%) |
| **Max Cost per Ticket** | $0.000712 | $0.000712 | Unchanged |
| **Mean Latency per Ticket** | 28,421.9 ms | 33,476.4 ms | +5,054.5 ms (+17.8%) |
| **Mean Tokens per Ticket** | 4,964.5 | 5,357.6 | +393.1 (+7.9%) |
| **Per-Mode Regressions** | 0 across 5 modes | 0 across 5 modes | **Zero Regressions** |
| **Injection Attack Resistance** | 0% (Breached) | 100% (Protected) | 3-Layer Defense Active |
