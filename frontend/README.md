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

## Layout

Atomic Design under `src/components/`: atoms → molecules → organisms → templates → pages.
