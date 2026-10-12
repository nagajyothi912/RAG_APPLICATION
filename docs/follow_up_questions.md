# Follow-up questions

Both chats (the customer chatbot and the admin console) handle follow-up questions in two ways:

1. **They understand follow-ups.** After "What does AirFiber_1199_1M include?", the message "and what about the 599 one?" is answered as "What does the AirFiber_599_1M plan include?".
2. **They suggest follow-ups.** Under the latest answer, up to three buttons offer other sections of the help articles the answer cited.

## The approach and why

| Decision | Chosen | Rejected, and why |
|---|---|---|
| Where history lives | The **browser** sends the last 6 messages with every request. The backend keeps no state. | Server-side sessions add storage, cleanup and per-user isolation for no gain here. History is lost on page reload, which is acceptable. |
| RAG chat (Week 3 / Week 4) | One extra Groq call **rewrites** the message into a standalone question before retrieval. | Only adding history to the answer prompt. Retrieval would still search for "how much is the 3M one?" and miss. |
| MCP assistant | History is passed to the agent as **earlier chat messages**. | A rewrite step. The agent already writes its own tool queries, so it resolves "it" itself, and an extra call would cost tokens against the 8k/min Groq limit. |
| Suggestions | **Other section headings of the cited articles.** No LLM call. | LLM-generated suggestions often invite questions the knowledge base can't answer, which then get refused. |

## How it works

```text
Browser (useChat)                         Backend
──────────────────                        ───────────────────────────────────────────
messages so far ──► history (last 6) ──►  /api/chat
                                            trim_history → rewrite_question (Groq, 1 call)
                                            → retrieve(standalone) → answer_with_groq(standalone)
                                            → suggest_follow_ups(cited sections)
                                          /api/assistant
                                            trim_history → agent.run(history=…)  (no rewrite)
                                            → suggest_follow_ups(cited help sources)
answer + follow_ups ◄──────────────────────
chips on the latest answer ──click──► sends the suggested question with the same engine/filters
```

### Rewrite (RAG chat only)

- This happens only when the request has history. **A request without history behaves exactly as before**: no extra call and the same prompt. All eval scripts call `ask()` without history, so the feature itself moves no reported number. The corpus change below does.
- The rewrite can't break a request. If the Groq call fails, returns nothing, or returns more than 400 characters (meaning it answered instead of rewriting), the message is searched as typed.
- Retrieval, the answer prompt and the refusal gate all use the standalone question. The gate is unchanged: the best dense cosine against `SCORE_THRESHOLD`.
- The answer prompt template is unchanged (same `PROMPT_SHA`). Only the question placed in it differs.
- `GROQ_TEMPERATURE` follows the usual rule: unset means no temperature is sent.
- **An ambiguous follow-up gets a guess, not a question back.** In a live test, "and how much is the 3M one?" after a question about AirFiber_1199_1M became "How much does the AirFiber_1199_3M plan cost?", a legacy plan, although AirFiber_1999_3M was another fair reading. Admin views show the "Follow-up searched as" line, so the guess is visible. The customer chatbot uses the Assistant, which doesn't rewrite.

### Suggestions

- These come from `suggest_follow_ups(chunks, cited)`.
- Sources are walked in ranked order. For each cited article, the function offers its sections except:
  - the **top 2 cited sections**, which are what the answer was about;
  - a bare article title, which is only the intro paragraph.
- The rest are offered, including sections retrieved at ranks 3–5. Top-5 retrieval over a short article cites every section, so skipping every cited section would leave nothing to suggest.
- Each chip's question is `Tell me about <section> (<article title>)`, for example `Tell me about Plan comparison (AirFiber broadband plans)`. It reuses the heading path every chunk is prefixed with, so it retrieves well in both modes.
- No suggestions appear on a refusal. Only the **latest** answer shows chips, and only while a question can be asked.
- Clicking a chip resends with that answer's options (engine, mode, top-k, filters).

### Which articles get suggestions

Suggestions come from `##` sub-headings, so **an article needs `##` sections to get chips**. A heading-free document, or one with only a `#` title, never gets suggestions. That applies to `.txt` files too: the heading chunker splits on `#` lines in any text file.

| Article | Sections offered |
|---|---|
| KB-001 AirFiber broadband plans | 3 plans, Plan comparison |
| KB-002 Billing and payments FAQ | Payment methods, Billing cycle and due dates, Failed payments, Invoices, Late fees |
| KB-003 Refund policy (`refund_policy.txt`) | Refund eligibility, What is not refundable, How refunds are paid, How to request a refund |
| KB-004 Troubleshooting connectivity | Router LED status reference, Error codes, Slow speed diagnosis, Official speed tests |
| KB-005 Installation and first-time setup | Before the appointment, Installation timelines, First-time setup, Mesh extender placement |
| KB-006 Account and plan management | 5 account sections |
| KB-007 Legacy and regional plans | 6 legacy plans, Legacy plan comparison, Migrating off a legacy plan |

No chips appear for a refused answer, for an Assistant answer that cited only tickets, when every section of the cited articles was among the top 2, or on any answer except the latest.

KB-002 and KB-003 had no sections at first, so they never got chips. Adding sections to them (see below) required two follow-up changes, and adding sections to any document will too:

1. **Update the Week 4 labels.** Chunk ids are numbered per document, so the labels in `backend/eval/golden_set.jsonl` that point into that document move. Recompute them with `build_chunks(..., chunk_size=1000, overlap=100, strategy="heading")`. `evaluate_week4.py` refuses to run if a label points at a missing chunk or one without its `answer_contains` text. Then re-run both eval scripts.
2. **Don't leave a tiny intro chunk.** Text between the `#` title and the first `##` becomes its own chunk. When KB-003's one-line "Effective date: 1 August 2026" became a chunk, "Who won the 2022 FIFA World Cup?" scored 0.150 against it and passed the 0.15 refusal gate (`test_clearly_unrelated_questions_are_refused_before_the_llm` caught it). Put intro lines inside the first section.

## Status: `results.md` still needs a re-run

The KB-002/KB-003 sections changed the corpus, and CLAUDE.md requires re-running both eval scripts after that. The re-run **has not been done yet**. The first attempt used up the Groq daily token quota (below) and was stopped before it wrote anything, so `results.md` still shows the numbers from before the sections were added. To finish, run both scripts one after the other with quota to spare, ideally with a key that the running app doesn't use:

```bash
# from backend/ - GROQ_API_KEY set in the shell overrides .env for this command only
GROQ_API_KEY=gsk_... python scripts/evaluate_retrieval.py
GROQ_API_KEY=gsk_... python scripts/evaluate_week4.py
```

Then check section 14 of `results.md`: the Week 4 ship/no-ship verdict has flipped on a corpus change before.

## Groq quota

- **Cost.** A RAG follow-up costs one extra Groq call (a few hundred tokens). An Assistant follow-up costs no extra call, but each request is a little larger because it carries up to 6 earlier messages.
- **Limits are per model and per Groq account**, not per key: on the free tier, 8,000 tokens per minute and 200,000 tokens per day for `gpt-oss-120b`. The eval scripts, the web app and any CLI run on the same account all draw from the same allowance. A second key from the same account adds nothing.
- **What hitting the daily cap looks like.** The chat shows "The assistant is handling too many requests right now (Groq rate limit). Please wait about a minute", which is misleading for a daily cap. The daily window is rolling, so capacity returns gradually.
- **Quickest fix.** `ASSISTANT_MODEL=openai/gpt-oss-20b` in `backend/.env` (then restart uvicorn; `--reload` doesn't watch `.env`) moves the Assistant to a model with its own allowance. Both models handle the Assistant's tool calls and `reasoning_effort`. The Week 3/4 chats and the eval scripts stay on `GROQ_MODEL`.

## API changes

All additions are optional, so old clients still work.

`POST /api/chat`. The request gains `history`. The response gains `rewritten_question` and `follow_ups`.

```json
{ "message": "and the 3M one?", "mode": "week4",
  "history": [ {"role": "user", "content": "What does AirFiber_1199_1M include?"},
               {"role": "assistant", "content": "200 Mbps unlimited…"} ] }
```

```json
{ "answer": "…", "sources": [ … ],
  "rewritten_question": "What is the price of the AirFiber_1999_3M plan?",
  "follow_ups": [ {"label": "Plan comparison",
                   "question": "Tell me about Plan comparison (AirFiber broadband plans)"} ] }
```

`rewritten_question` is `""` when the message was searched as typed.

`POST /api/assistant`. The request gains `history` and the response gains `follow_ups`, with the same shapes.

## Tracing

On a request with history, the trace record's `request.question` is the **rewritten** question, so `replay_trace.py` reproduces the retrieval. A new `request.follow_up` block holds:

```json
{ "original_question": "and the 3M one?", "history_messages": 2, "rewritten": true,
  "model": "openai/gpt-oss-120b", "error": null, "usage": {…}, "latency_ms": 412.3 }
```

Requests without history write no `follow_up` key, so their records are identical to before. The Week 9 agent trace gains `history_messages`.

## Limits (all in `backend/app/services/follow_up.py`)

| Constant | Value | Why |
|---|---|---|
| `MAX_HISTORY_MESSAGES` | 6 | Three exchanges. History is resent on every request. |
| `MAX_HISTORY_CHARS` | 1500 | Per message. Long answers are cut down. |
| `MAX_SUGGESTIONS` | 3 | Chips under one answer. |
| `ANSWERED_SECTIONS` | 2 | Top cited sections not offered again. |
| `REWRITE_MAX_TOKENS` | 600 | gpt-oss spends hidden reasoning tokens (a live rewrite used 275). |
| `MAX_REWRITE_CHARS` | 400 | Longer output is treated as unusable. |

The frontend's `HISTORY_MESSAGES` (`useChat.ts`) is 6 too. The backend cap is the one that counts.

## Files

| File | Change |
|---|---|
| `backend/app/services/follow_up.py` | **New.** `trim_history`, `rewrite_question`, `suggest_follow_ups`. |
| `backend/app/schemas.py` | `ChatTurn`, `FollowUpSuggestion`; `ChatRequest.history`; `ChatResponse.rewritten_question`, `.follow_ups`. |
| `backend/app/services/rag_service.py` | `ask(..., history=)` rewrites before calling `_ask_inner` and adds the suggestions afterwards; new `suggest_follow_ups()` method. **`_ask_inner`, `retrieve` and `answer_with_groq` are unchanged on purpose**: `test_week5_deliverables.py` pins them byte-for-byte to the Week 5 prediction commit. Keep follow-up logic out of them. |
| `backend/app/services/tracing.py` | `build_chat_record(follow_up=)` adds `request.follow_up`. |
| `backend/app/api/chat.py` | Passes `history`. |
| `backend/app/agents/week9/agent.py` | `run(history=)` inserts earlier turns between the system prompt and the question. It still names no server or tool. |
| `backend/app/services/assistant.py`, `backend/app/api/assistant.py` | `history` in, `follow_ups` out. |
| `backend/tests/test_follow_up.py` | **New.** 12 tests, none calling Groq. |
| `backend/tests/test_week9_mcp.py` | `test_assistant_endpoint`'s fake `ask` accepts `history` and checks that it arrives. |
| `sample_documents/help_centre/billing_faq.md`, `sample_documents/policies/refund_policy.txt` | `##` sections added (KB-002: 5, KB-003: 4), so they get suggestions. Existing sentences are unchanged. The refund policy keeps its `.txt` name, because about 20 files refer to it. |
| `backend/eval/golden_set.jsonl` | Week 4 labels moved with the new chunks: W03 `billing_faq.md#0→#2`, W04 `#0→#4`, W06 `refund_policy.txt#0→#1`. W05 stays `#0`. |
| `frontend/src/services/api.ts` | `ChatTurn`, `FollowUpSuggestion` types; `sendChat` / `sendAssistant` take `history`. |
| `frontend/src/hooks/useChat.ts` | Builds history from the conversation so far. |
| `frontend/src/components/molecules/MessageBubble.tsx` | Follow-up chips; "Follow-up searched as" line in admin views. |
| `frontend/src/components/organisms/ChatWindow.tsx` | Gives the chips' click handler to the latest answer only. |
| `frontend/src/index.css` | `.follow-ups`, `.follow-up-chip`, `.rewritten-question`. |

## How to check it

```bash
# from backend/
pytest tests/test_follow_up.py -v
```

Manually, with the app running, open the admin home chat with the **Week 4** engine:

1. Ask "What does AirFiber_1199_1M include?" Chips appear under the answer.
2. Ask "and what about the 599 one?" The answer shows **Follow-up searched as** with a standalone question naming AirFiber_599_1M, and the sources include that plan's section.
3. Click a chip. It is sent as a new question with the same engine.
4. Switch to **Assistant** and ask "When was it opened?" right after a ticket question. The agent should look up the same ticket.
5. In the customer chatbot, steps 1 and 3 should behave the same (the label reads "You might also ask").
6. Ask "When is my bill generated?" Chips such as "Failed payments" and "Late fees" appear. Before the KB-002 sections were added, billing answers showed none.

## Possible next steps

- **LLM-written suggestions for the Assistant.** Ticket answers currently get no chips, because they cite no help article.
- **Persisting conversations** server-side, if history should survive a reload. That needs per-user scoping.
- **An accurate rate-limit message.** Tell a daily-cap 429 apart from a per-minute one in `assistant.py` (Groq's error body says "tokens per day"), and don't tell the user to wait a minute when the wait is hours.
- **A follow-up eval.** Add multi-turn cases to a fixture and measure retrieval hit rate on the rewritten question against the typed one. Don't add them to `golden_set.jsonl`, whose labels are single-turn.
