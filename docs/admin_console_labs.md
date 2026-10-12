# Admin console: home view and the Labs switch

The admin console used to open on a row of eight week tabs (Week 3 … Week 8, Week 9, Chatbot). It now opens on one **home** view that does the day-to-day admin work. The week pages are **course labs**: hidden behind a **Labs** switch in the header, never removed.

```text
AF  Ask My Documents · Admin console        [● Labs] [Course labs ▾]   ● admin ADMIN [Sign out]
────────────────────────────────────────────────────────────────────────────────────────────────
 Sidebar                          │  Chat
 · Upload (drag files/folders)    │  Answer with: [Assistant] [Hybrid RAG] [Dense RAG]
 · Indexed library                │  …conversation…
 · MCP servers                    │
 · Common questions               │
```

## Why

- **Admins weren't using the week tabs.** Uploading documents, checking the library, seeing which MCP servers are live and asking questions were spread over the Week 3, Week 4 and Week 9 tabs. The home view puts them on one screen.
- **The weeks still need to exist.** They're course deliverables, graders open them by URL, and the Week 5 write-ups link to `#analysis/TR-0055`. So they're **hidden, not removed**, and every lab URL works whether the switch is on or off.
- **One chat replaces three.** The Week 3, Week 4 and Week 9 chats asked the same questions through different engines. The home chat's **Answer with** control picks the engine per question, and each message is labelled with how it was answered, so one conversation can compare them.

## How it works

### The Labs switch: `hooks/useLabsSwitch.ts`

- `useLabsSwitch()` returns `{ showLabs, setLabs }`. It is **off by default**.
- It's stored in `localStorage` under `ask-my-documents.show-labs`, per browser. Every read and write is in `try/catch`: in a private window or with site data blocked, the switch starts off and lasts for that page load only.
- It controls one thing: whether the header shows the **Course labs ▾** menu. It does **not** gate routing.

### Routing: `pages/AdminConsole.tsx`

- Views are hash-routed. `parseHash()` maps the hash to a view, and anything unknown, including no hash, goes to `home`.
- `LABS` is the single list of labs: id, hash, label and caption. The menu, the routing and the lab bar all read from it.

| View | Hash | Page |
|---|---|---|
| Home (default) | `#home` or none | `AdminHome` |
| Week 3 · Baseline RAG | `#week3` | `RagPage variant="week3"` |
| Week 4 · Hybrid retrieval | `#week4` | `RagPage variant="week4"` |
| Week 5 · Error analysis | `#analysis` (`#analysis/<trace id>` opens a trace) | `ErrorAnalysisPage` |
| Week 6 · Judge validation | `#week6` | `Week6Page` |
| Week 7 · Agent vs workflow | `#week7` | `Week7Page` |
| Week 8 · Trajectory evals | `#week8` | `Week8Page` |
| Week 9 · MCP agent | `#week9` | `RagPage variant="week9"` |
| Chatbot · What users see | `#chatbot` | `RagPage variant="chatbot"` |

- Week 5 keeps `#analysis` rather than `#week5`, so existing links and the hash the error-analysis page writes when a trace is opened keep working.
- **Lab links open even with the switch off.** When a lab is open, a lab bar shows **← Console**, the lab's name and, if the switch is off, "Course labs are hidden. **Show**".
- **Chats keep their conversation.** The home view and the chat labs (`week3`, `week4`, `week9`, `chatbot`; `KEEP_MOUNTED`) are mounted the first time they're opened. After that they're hidden with `hidden`, not unmounted, so switching views doesn't lose a conversation. Weeks 5–8 are mounted only while open.

### The labs menu: `molecules/LabsMenu.tsx`

This is a dropdown with one entry per lab, showing the label, the caption and the current lab marked with `aria-current`. It closes on an outside click, on Escape, or once a lab is picked.

### The home view: `pages/AdminHome.tsx`

**Sidebar**
- **Upload** (`FileUpload`/`FileSelector`): choose files, choose a folder, or **drag and drop** files or whole folders. A dropped folder is walked recursively, and each file is given the same `webkitRelativePath` the folder picker sets, so sub-folder names survive either way.
- **Indexed library** (`DocumentList`), with delete.
- **MCP servers** (`McpServersPanel`): what the assistant discovered. On the home view it hides its own example list (`examples` and `onAsk` are optional now), because the examples live in Common questions.
- **Common questions** (`organisms/CommonQuestions.tsx`): every shortcut the week chats offered, in one place. Picking one **fills the box and sets the engine**; nothing is sent until **Send**.
  - **Tickets** and **assistant examples** switch to Assistant. Tickets are reachable only through the MCP ticket-history server.
  - **Golden questions** keep the current engine. Under RAG they're scoped to their document, shown as a "Scoped to … · Search all documents" chip.
  - **The Week 3 vs Week 4 pair** switches from Assistant to Dense RAG, unscoped. **Compare** asks the question under Week 3 and then Week 4, one after the other.
  - The example lists live in `data/exampleQuestions.ts` (`TICKET_QUESTIONS`, `ASSISTANT_EXAMPLES`) and are shared with the Week 9 lab and the chatbot.

**Chat:** `ChatWindow variant="admin"`
- **Answer with** (`molecules/EngineSelect.tsx`) offers `ChatEngine = 'assistant' | 'week4' | 'week3'`: **Assistant** (MCP, help centre and tickets), **Hybrid RAG** (Week 4), **Dense RAG** (Week 3). If BM25 or the reranker is missing it shows a warning instead of hiding Hybrid. Hybrid still runs, just as dense-only.
- `ChatInput` turns the engine into `AskOptions`: Assistant sets `agent: true` and drops the retrieval scope, and the RAG engines set `mode`. A document scope picked from Common questions applies to that one question and is cleared after sending.
- Each user message shows how it was asked (an "Assistant · MCP" badge, or mode, top-k and filters).
- The input can't send while RAG is selected and nothing is indexed, but the engine can still be switched to Assistant.

### Shared types: `services/api.ts`

- `ChatVariant` gains `'admin'`, with `VARIANT_MODE.admin = 'week4'`.
- New `ChatEngine` type.
- Chat UI differences come from the `ChatVariant` prop, not from separate components, as before.

## Files

| File | Change |
|---|---|
| `frontend/src/hooks/useLabsSwitch.ts` | **New.** The persisted on/off switch. |
| `frontend/src/components/molecules/LabsMenu.tsx` | **New.** The "Course labs" dropdown. |
| `frontend/src/components/pages/AdminConsole.tsx` | Week tabs replaced by home view, Labs switch, labs menu, lab bar and hash routing. |
| `frontend/src/components/pages/AdminHome.tsx` | **New.** Sidebar and one chat. |
| `frontend/src/components/organisms/CommonQuestions.tsx` | **New.** Grouped question shortcuts. |
| `frontend/src/components/molecules/EngineSelect.tsx` | **New.** The "Answer with" control. |
| `frontend/src/data/exampleQuestions.ts` | **New.** Ticket and assistant examples, moved out of `RagPage`. |
| `frontend/src/components/molecules/ChatInput.tsx` | `admin` variant: engine, prefill from the sidebar, one-question scope chip. |
| `frontend/src/components/molecules/RetrievalControls.tsx` | `leading` slot for the engine selector. |
| `frontend/src/components/molecules/FileSelector.tsx` | Drag-and-drop zone, including folders. |
| `frontend/src/hooks/useDocuments.ts` | `addFiles` accepts `File[]` (from a drop) as well as `FileList`. |
| `frontend/src/components/organisms/McpServersPanel.tsx` | Example list optional. |
| `frontend/src/components/organisms/ChatWindow.tsx`, `MessageBubble.tsx` | `admin` header copy, and an "Assistant · MCP" badge on agent-answered questions. |
| `frontend/src/components/pages/RagPage.tsx`, `organisms/FileUpload.tsx` | Use the shared example lists; small prop changes. |
| `frontend/src/index.css` | `.labs-switch`, `.labs-menu`, `.lab-bar`, `.admin-sidebar`, `.common-*`, `.chat-window--admin`, drop-zone styles. |

There are no backend changes: every lab still calls the same `/api/*` routes with the same role checks.

## How to check it

There's no frontend test runner. `npm run build` (which runs `tsc --noEmit`) is the correctness gate. Manually:

1. Sign in as admin. The console opens on **home** with the Labs switch **off** and no Course labs menu.
2. Open `#week8` in the address bar. The Week 8 lab opens, and the lab bar says the labs are hidden. **Show** turns the switch on.
3. Turn **Labs** on and reload. It stays on. Pick **Week 5** from Course labs: the URL is `#analysis`.
4. On home, pick a ticket question in Common questions. The engine switches to **Assistant** and the box fills, but nothing is sent until **Send**.
5. Ask something on home, open a lab, then **← Console**. The conversation is still there.
6. Drag a folder onto Upload. Its files are listed with their sub-folder paths.

## Extending it

- **Adding a lab:** add a `LabDef` to `LABS` with a unique `hash`, add the page to `AdminConsole`'s `<main>`, and add the id to `KEEP_MOUNTED` if it's a chat that should keep its conversation.
- **Removing a lab:** don't. Old links, Week 5's `#analysis/…` and the graded deliverables depend on them. Hide labs; never delete them.
