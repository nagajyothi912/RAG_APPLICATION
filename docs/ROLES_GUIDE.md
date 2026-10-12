# Signing in: the User (chatbot) and Admin roles

**In short:** the app has two kinds of login. A **User** gets the *AirFiber Support Assistant*, a single chat where customers ask questions about their AirFiber service. They get answers from the help centre, with the source article for each answer. An **Admin** gets the *Admin console*. It opens on a home view with document upload and delete, the MCP servers, common questions and one chat that can answer with the assistant or either RAG pipeline. The week-by-week course labs (Weeks 3–9 and a preview of what users see) are behind a **Labs** switch. The backend checks the role on every request, so a User cannot reach admin data even by calling the API directly.

---

## Contents

1. [Which role is for whom](#1-which-role-is-for-whom)
2. [Signing in](#2-signing-in)
3. [User guide: the AirFiber Support Assistant](#3-user-guide-the-airfiber-support-assistant)
4. [Admin guide: the Admin console](#4-admin-guide-the-admin-console)
5. [Who can do what](#5-who-can-do-what)
6. [Setting up the accounts](#6-setting-up-the-accounts)
7. [How it works](#7-how-it-works)
8. [Troubleshooting](#8-troubleshooting)
9. [Files](#9-files)

---

## 1. Which role is for whom

| | **User** (internal name `chatbot`) | **Admin** |
| --- | --- | --- |
| Who | A customer, or a support agent answering customers | The person who runs the knowledge base and the evaluations |
| What they want | An answer to a question: "Why is my LED blinking red?", "Is there a late fee?" | To change which articles the assistant knows, and to see how well each week's work performed |
| What they see | One chat screen, plain language, no technical controls | A home view (library, MCP servers, one chat with a choice of engine), plus course labs for Weeks 3–9 and a Chatbot preview behind a **Labs** switch |
| Answers use | The full pipeline every week built (see [§3.5](#35-what-happens-behind-the-scenes)) | Whichever engine is picked in **Answer with**, or the pipeline the lab is about |

The role is called **User** on screen and `chatbot` in code, config and the API. They are the same thing.

---

## 2. Signing in

Open the app (http://localhost:5173 in development). You will see the **Ask My Documents** sign-in card.

1. Under **Sign in as**, pick **User** or **Admin**.
2. Enter the username and password.
3. Click **Start chatting** (User) or **Sign in to admin console** (Admin).

Default accounts. Change them before anyone else uses the app ([§6](#6-setting-up-the-accounts)):

| Role | Username | Password |
| --- | --- | --- |
| User | `user` | `user123` |
| Admin | `admin` | `admin123` |

Things to know:

- **The role you pick must match the account.** If you pick *Admin* and enter the User account, sign-in fails with *"This account signs in as chatbot, not admin."* Nobody lands in the wrong app by mistake.
- **You stay signed in** across page reloads, until the session expires (8 hours by default) or you click **Sign out**.
- **If the session ends** (it expired, or the server restarted without a fixed `AUTH_SECRET`), the next request takes you back to the sign-in card with *"Your session ended. Sign in again."*

---

## 3. User guide: the AirFiber Support Assistant

### 3.1 The screen

```
┌──────────────────────────────────────────────────────────────────────────┐
│ AF  AirFiber Support Assistant          [New chat] ● user USER [Sign out]│
├──────────────────┬───────────────────────────────────────────────────────┤
│ I can help with  │  AIRFIBER SUPPORT                                     │
│  Your account    │  How can we help today?                               │
│  Billing, pay... │                                                       │
│  Installation... │   (conversation)                                      │
│  Plans and pri...│                                                       │
│  Connection p... │                                                       │
│ Common questions │  [ Ask about plans, billing, installation or ...] Send│
│  [What speed...] │                                                       │
└──────────────────┴───────────────────────────────────────────────────────┘
```

| Part | What it does |
| --- | --- |
| **I can help with** | The topics the help centre covers, with how many articles each has. They come from the articles an admin has uploaded, so the list changes when the library changes. |
| **Common questions** | Click one to ask it straight away, searching every topic. |
| **Ticket questions** | Clickable examples that ask about a support ticket ([§3.6](#36-asking-about-a-support-ticket)). |
| **Message box** | Type your question. **Enter** sends it and **Shift + Enter** adds a new line. |
| **New chat** | Clears the conversation. |
| **Sign out** | Ends the session and returns to the sign-in card. |

### 3.2 Asking a question

Ask in your own words, the way you would ask a support agent. Specific details help, especially plan names and error codes:

- *What does a blinking red LED on the AirFiber ONT mean?*
- *Does the AirFiber_599_1M plan include a mesh extender or an OTT bundle?*
- *What happens if my auto-pay payment fails?*
- *Is there a late fee on prepaid packs?*

### 3.3 Reading an answer

- The answer can include **bold** text, bullet lists and tables.
- Under the answer, **From N help articles** lists where it came from. Click it to see each article's name, its ID (for example `KB-004`), topic, section, a short preview and when it was last updated.
- **Check the article if it matters.** The answer is written by an AI model from those passages. The source list lets you confirm it.

### 3.4 When the assistant says it doesn't know

The assistant answers **only** from the help centre. If the help centre does not cover your question, it says so instead of guessing, for example *"I don't know based on the provided documents."* There are two reasons this happens:

1. **Nothing relevant was found.** The best match scored below the confidence threshold, so the AI model was not even asked.
2. **Something was found but it doesn't answer the question.** The model read the passages and declined to answer.

What to try:

- Rephrase using the words the help centre would use: the plan name, the LED colour, the error code.
- Name the topic in the question ("billing", "installation").
- Ask a narrower question ("late fee on prepaid packs" rather than "tell me about billing").
- If it is genuinely not covered, contact human support. The assistant cannot help with things outside the articles.

> The same question can get a slightly different answer each time, and occasionally an answer one time and a refusal the next. This happens because the model runs at Groq's default randomness. An admin can make answers repeatable by setting `GROQ_TEMPERATURE=0` ([§6](#6-setting-up-the-accounts)).

### 3.5 What happens behind the scenes

The customer chatbot is the **Week 9 MCP agent**. Instead of one fixed search, the model decides which tools to call:

```
your question ──► Groq model reads the 5 tool descriptions (discovered over MCP)
                      │
                      ├─► help-centre server (in-process)   search_help_centre, get_article
                      │      └─ Week 4 retrieval: BM25 + dense, RRF, cross-encoder rerank
                      └─► ticket-history server (stdio)     list_tickets, lookup_ticket, get_escalation_history
                      │
                  …repeats until it has what it needs (max 8 tool turns, then it must answer)…
                      ▼
   reply in plain words, mentioning the article ids it used
```

- The help-centre search is still the Week 4 pipeline, now reached through MCP.
- **The Week 3 refusal gate (score < 0.15 → "I don't know") does not apply here.** The search tool returns the best passages whatever their score, and the *model* decides whether they answer the question. The Week 3 and Week 4 admin tabs still use the gated `/api/chat`.
- Assistant questions are **not** written to the Week 5 trace log. Ticket lookups are logged in `backend/data/ticket_history_access.log`.
- The **Topic** filter, Week 3/4 toggle, top-k and golden set are not shown; the assistant picks its own search area.
- An answer typically takes 2–10 seconds: one to three model turns, plus tool calls of a few milliseconds each.

### 3.6 Asking about a support ticket

The assistant can also answer from the **ticket system** (the Week 9 ticket-history MCP server): status, contact count, order and install status, and escalation history. Give the id (*"Has anyone called back the customer on ticket TCK-4471?"*), or describe the ticket (*"the relocation complaint that has been open for six weeks"*) and the assistant finds it first. The sidebar's **Ticket questions** are clickable examples. The ids in the sample data are TCK-4471, TCK-4410, TCK-4519, TCK-4518 and TCK-4422.

- **Any signed-in user can ask about any ticket.** Logins aren't linked to customers, so every User can see every customer's name, phone and payments. That's fine for this fictional data, and would not be for real customers.
- Every ticket lookup is logged with **who asked** (`caller=user/chatbot`) in `backend/data/ticket_history_access.log`.
- The assistant only **looks things up**. It's told never to promise callbacks, refunds or reschedules.

### 3.7 What a User cannot do

Upload, delete or rename articles, or open any week's evaluation pages. The interface doesn't offer these, and the server refuses them (HTTP 403) if they are attempted directly.

---

## 4. Admin guide: the Admin console

### 4.1 The screen

```
AF  Ask My Documents · Admin console     [● Labs] [Course labs ▾]   ● admin ADMIN  [Sign out]
──────────────────────────────────────────────────────────────────────────────────────────
 Upload · Indexed library ·           │  Answer with: [Assistant] [Hybrid RAG] [Dense RAG]
 MCP servers · Common questions       │  …chat…
```

The console opens on **home**:
- **Left:** the knowledge base, the MCP servers and **Common questions**. Picking a question fills the chat box and picks what answers it; nothing is sent until **Send**.
- **Right:** one chat. **Answer with** chooses the engine for each question: the **Assistant** customers use (help centre and tickets), **Hybrid RAG** (Week 4) or **Dense RAG** (Week 3). Every message is labelled with how it was answered.

The week pages are **course labs**. Turn on the **Labs** switch to get the **Course labs ▾** menu; your browser remembers the setting. Each lab has its own web address (`#week3` … `#week9`, `#chatbot`), and those addresses **work even with the switch off**, so bookmarks and shared links still open. Week 5 uses `#analysis`, so older links such as `#analysis/TR-0055` still open that trace. **← Console** returns to home. The chats (home, Week 3, Week 4, Week 9, Chatbot) keep their conversation when you switch views. How it's built: [admin_console_labs.md](admin_console_labs.md).

### 4.2 Managing the help centre (home, and the Week 3 and Week 4 labs)

The left column of the home view, and of the Week 3 and Week 4 labs, is the knowledge base. Changes here change what the User assistant knows, immediately.

- **Upload:** **Choose files** or **Choose folder** (`.txt`, `.md` and `.pdf`), or drag files or folders onto the upload box, then **Upload & index**. Folder upload keeps sub-folder names, and the top-level folder becomes the article's topic if the file has no front-matter.
- **Delete:** **Delete** next to an article removes it and rebuilds the index.
- **Front-matter matters.** `article_id`, `product_area` and `last_updated` at the top of a Markdown file become the citation ID, the topic shown in the User's "I can help with" list, and the "last updated" date. The sample articles are in [`sample_documents/`](../sample_documents/).

### 4.3 The course labs, week by week

| Lab | What it shows | What you can do | Learn more |
| --- | --- | --- | --- |
| **Week 3 · Baseline RAG** | Chat locked to the original pipeline: meaning search (dense) only, the refusal gate, citations with scores | Ask questions; change **Top K** and **Product area**; use the **Golden set of questions**; manage documents | [WEEK3_GUIDE](week3/WEEK3_GUIDE.md) |
| **Week 4 · Hybrid retrieval** | The same chat with the **Week 3 / Week 4** retrieval toggle. Answers show per-stage scores (dense, BM25, rerank) and how re-ranking moved each passage | Flip the toggle on the same question to compare; golden questions **G13/G14** are refused under Week 3 and answered under Week 4 | [WEEK4_GUIDE](week4/WEEK4_GUIDE.md) |
| **Week 5 · Error analysis** | The failure taxonomy and a searchable list of the 148 traced requests | Click a failure mode to filter, search, open a trace to see its retrieval, the exact prompt and raw output; switch **Trace file** between the committed run and the live server log | [WEEK5_GUIDE](week5/WEEK5_GUIDE.md) |
| **Week 6 · Judge validation** | How often the AI judge agrees with blind human labels: v1 single run (92.3%), v1 majority of 3 (96.2%), v2 majority of 3 (96.2%), plus held-out agreement and the committed prediction | Tick **Only disagreements**; click a ticket to read each judge's explanation. Read-only, from `backend/eval/week6/runs/` | [WEEK6_GUIDE](week6/WEEK6_GUIDE.md) |
| **Week 7 · Agent vs workflow** | The ticket-reply agent compared with the fixed workflow: **Comparison Table**, **Budget Log**, **Third Tool Diff** | **▶ Run Experiment**, **⚡ Budget Test**, **↻ Refresh** | [WEEK7_GUIDE](week7/WEEK7_GUIDE.md) |
| **Week 8 · Trajectory evals** | Five sub-tabs: the four trajectory numbers, the 10 cases and their allowed paths, the single fix and its cost, the per-mode regression check, and the prompt-injection bonus | **▶ Run Evaluation**, **↻ Refresh Data**, **⚡ Re-run Attack Simulation** | [WEEK8_GUIDE](week8/WEEK8_GUIDE.md) |
| **Week 9 · MCP agent** | The same assistant customers use, with the MCP servers it discovered (server, transport, tools) in the sidebar and every `tools/call` shown under each answer: server, tool, arguments, ok/isError, latency | Click a **Try** example or ask about a ticket or the help centre | [WEEK9_GUIDE](week9/WEEK9_GUIDE.md) |
| **Chatbot · What users see** | Exactly the User assistant, including the help sidebar | Check what a customer will experience after changing the library | [§3](#3-user-guide-the-airfiber-support-assistant) |

**The run buttons call Groq and cost tokens.** Week 7 **Run Experiment**, Week 7 **Budget Test**, Week 8 **Run Evaluation** and Week 8 **Re-run Attack Simulation** all call the model. They run in the background and **overwrite the committed results files** in `eval/week7/` and `eval/week8/`, so the numbers on the page change. Press **Refresh** when they finish. If you only want to review the results, don't press them.

> Some Week 8 numbers in its README and demo docs don't match the committed results file, and part of the page (the T017 deep-dive) is fixed text. See [WEEK8_GUIDE §6](week8/WEEK8_GUIDE.md) before quoting them.

---

## 5. Who can do what

Enforced by the backend on every request. Hiding something in the interface is not the only protection.

| Action | Signed out | User | Admin | API route |
| --- | :-: | :-: | :-: | --- |
| Check the server is up | ✅ | ✅ | ✅ | `GET /api/health` |
| Sign in / see who I am | ✅ / — | ✅ | ✅ | `POST /api/auth/login`, `GET /api/auth/me` |
| Ask a question (Week 3/4 RAG tabs) | ❌ 401 | ✅ | ✅ | `POST /api/chat` |
| Ask the assistant (help centre + **any** ticket) | ❌ 401 | ✅ | ✅ | `POST /api/assistant` |
| See the MCP servers and tools | ❌ 401 | ❌ 403 | ✅ | `GET /api/assistant/servers` |
| See the article list and topics | ❌ 401 | ✅ | ✅ | `GET /api/documents` |
| See golden / common questions | ❌ 401 | ✅ | ✅ | `GET /api/golden-questions` |
| Upload articles | ❌ 401 | ❌ 403 | ✅ | `POST /api/documents/upload` |
| Delete an article | ❌ 401 | ❌ 403 | ✅ | `DELETE /api/documents?name=` |
| Week 5 error analysis | ❌ 401 | ❌ 403 | ✅ | `GET /api/analysis/*` |
| Week 6 judge results | ❌ 401 | ❌ 403 | ✅ | `GET /api/week6/results` |
| Week 7 results and runs | ❌ 401 | ❌ 403 | ✅ | `/api/week7/*` |
| Week 8 results and runs | ❌ 401 | ❌ 403 | ✅ | `/api/week8/*` |

**401** means "sign in first", and the app returns you to the sign-in card. **403** means "signed in, but this role is not allowed".

---

## 6. Setting up the accounts

All settings live in `backend/.env` (copy `backend/.env.example`). Restart the backend after changing them.

| Variable | Default | What it does |
| --- | --- | --- |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin123` | The admin account |
| `CHATBOT_USERNAME` / `CHATBOT_PASSWORD` | `user` / `user123` | The User account |
| `AUTH_SECRET` | empty, so a random value per server start | Signs the session tokens. **Set it to a long random string**, otherwise every server restart signs everyone out. |
| `AUTH_TOKEN_TTL_MINUTES` | `480` | How long a sign-in lasts (8 hours) |
| `AUTH_ENABLED` | `true` | Leave on. `false` treats every request as admin, and only the test suite uses it. |
| `GROQ_TEMPERATURE` | unset (Groq's default) | Set `0` for repeatable User answers ([§3.4](#34-when-the-assistant-says-it-doesnt-know)) |

Generate a secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

On startup the server logs a warning while either default password is still in use.

**Limits of this setup:** there is exactly one account per role. Passwords live in `.env` in plain text, and there is no sign-up, password reset or per-user history. That is fine for a course demo or a single team. A real customer deployment would need a user database or an identity provider.

---

## 7. How it works

```
 Sign-in card ──POST /api/auth/login {username, password, role}──► backend checks the account
                                                                   and that role matches
            ◄── { token, expires_at, user:{username, role} } ──────┘
 token saved in the browser (localStorage)
 every request:  Authorization: Bearer <token>
                 backend verifies the signature + expiry, then
                 current_user (any role) or require_admin (admin only)
 on reload:      GET /api/auth/me decides which app to show
 on any 401:     token cleared, back to the sign-in card
```

- **Token format:** `<payload>.<signature>`. The payload holds the username, role and expiry; the signature is HMAC-SHA256 with `AUTH_SECRET`. It uses only the Python standard library, with no JWT package. Changing one character, for example swapping the role to `admin`, breaks the signature, and the server rejects the token.
- **Which app shows** is decided by the role the **server** confirms, never by what the browser stored.
- **One page component, three variants.** The User assistant and the Week 3 and Week 4 admin tabs are the same chat page with a `variant` setting:

| | `chatbot` (User) | `week3` (Admin) | `week4` (Admin) |
| --- | --- | --- | --- |
| Retrieval mode | fixed `week4` | fixed `week3` | toggle |
| Top K / golden set | hidden | shown | shown |
| Sidebar | help topics + common questions | upload + library | upload + library |
| Citations | article name, section, preview | file, chunk #, all scores | file, chunk #, all scores |

---

## 8. Troubleshooting

| What you see | Why | Fix |
| --- | --- | --- |
| *Incorrect username or password.* | Wrong credentials | Check `backend/.env`. Passwords are case-sensitive. |
| *This account signs in as chatbot, not admin.* (or the reverse) | The role picked on the card doesn't match the account | Pick the other role card |
| *Your session ended. Sign in again.* | Session expired, or the server restarted without `AUTH_SECRET` | Sign in again; set `AUTH_SECRET` so restarts don't sign people out |
| User sees *The help centre is empty right now…* | No articles are indexed | An admin uploads articles on the console home (or the Week 3/4 lab), e.g. the `sample_documents/` folder |
| User sees *The assistant is offline right now.* | The backend isn't reachable | Start it: `cd backend && uvicorn app.main:app --reload --port 8000` |
| Every page asks for sign-in after updating the code | The backend now requires login | Expected. Sign in with the accounts in [§2](#2-signing-in). |
| A script or `curl` gets 401 | It sends no token | Log in first: `curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}'`, then send `Authorization: Bearer <token>` |
| Week 7/8 numbers changed | Someone pressed a run button, which overwrote the results files | `git diff eval/` shows what changed; `git checkout eval/week7 eval/week8` restores the committed results |
| An answer is wrong or a good question is refused | Retrieval or model behaviour, not the role system | Ask it in the admin home chat with **Hybrid RAG** (or the **Week 4** lab) to see which passages were retrieved and their scores; the **Week 5** lab explains the known failure modes |

---

## 9. Files

| File | Purpose |
| --- | --- |
| [`backend/app/services/auth.py`](../backend/app/services/auth.py) | Accounts, token signing and checking, the `current_user` / `require_admin` guards |
| [`backend/app/api/auth.py`](../backend/app/api/auth.py) | `POST /api/auth/login`, `GET /api/auth/me` |
| [`backend/app/main.py`](../backend/app/main.py) | Which route groups need sign-in and which need admin |
| [`backend/app/api/documents.py`](../backend/app/api/documents.py) | Per-route guards: health public, listing signed-in, upload and delete admin |
| [`backend/app/api/week6.py`](../backend/app/api/week6.py) | Read-only Week 6 judge results for the admin tab |
| [`backend/tests/test_auth.py`](../backend/tests/test_auth.py) | Tests for the access rules, wrong role, tampered and expired tokens |
| [`frontend/src/App.tsx`](../frontend/src/App.tsx) | Shows the sign-in card, the User app or the Admin console |
| [`frontend/src/hooks/useAuth.ts`](../frontend/src/hooks/useAuth.ts) | Sign in, sign out, restore the session on reload |
| [`frontend/src/components/pages/LoginPage.tsx`](../frontend/src/components/pages/LoginPage.tsx) | The sign-in card |
| [`frontend/src/components/pages/ChatbotApp.tsx`](../frontend/src/components/pages/ChatbotApp.tsx) | The User assistant |
| [`frontend/src/components/organisms/HelpSidebar.tsx`](../frontend/src/components/organisms/HelpSidebar.tsx) | "I can help with" and "Common questions" |
| [`frontend/src/components/pages/AdminConsole.tsx`](../frontend/src/components/pages/AdminConsole.tsx) | The admin console: home view, Labs switch, course labs ([admin_console_labs.md](admin_console_labs.md)) |
| [`frontend/src/components/pages/Week6Page.tsx`](../frontend/src/components/pages/Week6Page.tsx) | The Week 6 tab |
| [`frontend/src/components/atoms/RichText.tsx`](../frontend/src/components/atoms/RichText.tsx) | Safe display of bold, lists and tables in answers |

Run the access-rule tests:

```bash
cd backend && pytest tests/test_auth.py -v
```
