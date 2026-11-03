# Bonus: AgentCard and the failed case on the A2A task lifecycle

The orchestrator's AgentCard is [agent_card.json](agent_card.json). It declares two skills (`draft-ticket-reply`, `triage-ticket`), JSON and text as input/output modes, bearer-token auth (the app's HMAC-signed session token, admin role), and push notifications for tasks that pause.

## T017 with the policy worker down: `failed` or `input-required`?

**`input-required`, waiting for the ticket owner.** It should not end `failed`.

| Step | What happened in the run | A2A state it should map to |
|---|---|---|
| Ticket arrives | orchestrator accepts it | `submitted` |
| Decompose, triage, policy hand-off | triage succeeds and escalates; policy returns 500 twice | `working` (the policy sub-task itself ends `failed`) |
| Synthesis | sent a cut-off partial reply to the customer | **`input-required`**: "Policy lookup unavailable. Confirm refund eligibility for ₹1999 or resume when the policy service is back." The triage artifact (account record, escalation to the Priority Support Lead) is attached. |
| Ticket owner answers / service recovers | — | `working`, then `completed` with the reply as the artifact |

Why not `failed`: half the work succeeded, and a Priority customer asking about money already has a named owner thanks to the escalation. `failed` throws that away and makes the caller start over. Why not `completed`: the run did that, and it sent a reply that neither answered the refund question nor said it couldn't.

## What A2A buys over a plain REST call to the worker

A REST 500 gave the orchestrator a status code and no meaning, so it had to guess whether to retry, degrade or stop, and it guessed "send something". A2A gives a typed task lifecycle (`failed` vs `input-required` vs `auth-required`), long-running tasks with push notifications, and an AgentCard for discovery and auth, so "pause and ask a human" is a protocol state rather than custom glue.
