# Frontend

React + TypeScript UI for document upload and chat. Talks only to the FastAPI backend through `src/services/api.ts`.

## How to run

Start the backend first (see `backend/README.md`), then:

```bash
cd frontend
npm install
npm run dev
```

This project uses Node.js 18+ (`node`, `npm`). If `npm` is not found, install Node or put it on your `PATH` (this machine uses `~/.local/node` linked into `~/.local/bin`).

Open http://localhost:5173

Vite proxies `/api` to `http://127.0.0.1:8000`, so you do not need a frontend env file in development.

## Scripts

```bash
npm run dev      # local UI
npm run build    # typecheck + production bundle
```

There is no linter and no test runner here. `npm run build` runs `tsc --noEmit` first, so it is the correctness gate.

## Layout

Atomic Design under `src/components/`: atoms → molecules → organisms → templates → pages.

## Features

- **Citations.** `MessageBubble` renders every retrieved chunk under the answer with its `article_id`, `product_area`, section path, similarity score, and preview.
- **Metadata filter.** The product-area dropdown beside Send restricts retrieval to one `product_area`; the list comes from `/api/documents`.
- **Document metadata.** The indexed library shows each file's article ID, product area, chunk count, and last-updated date.
