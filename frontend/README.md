# MedAgent frontend

Next.js (App Router) + TypeScript + Tailwind + shadcn/ui. A chat UI over the MedAgent API with live
agent steps, source citations, a booking confirmation card, safety cards, "My appointments" and an
"Add to calendar" (.ics) download. Decisions: [ADR 0011](../docs/adr/0011-frontend.md).

## Run it

```powershell
# 1. the API (from the repo root; needs the database and .env, see docs/SETUP.md)
docker compose up -d
uv run python scripts/serve.py          # http://localhost:8000

# 2. the frontend
cd frontend
npm ci
npm run dev                             # http://localhost:3000
```

`NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) is the API address, baked in at build time.
The API must allow the frontend's origin: `API_CORS_ORIGINS=http://localhost:3000` (the default).

## Scripts

| Command                                       | What it does                                                                                  |
| --------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `npm run lint` / `typecheck` / `format:check` | ESLint, `tsc`, Prettier                                                                       |
| `npm test`                                    | Vitest: SSE parser, event decoding, citation parser, `.ics` builder                           |
| `npm run e2e`                                 | Playwright smoke test against a mock API (`tests/e2e/mock-api.mjs`): no database, key or cost |
| `npm run screenshots`                         | Regenerates `docs/screenshots/` (production build, desktop and mobile, light and dark)        |

First time only: `npx playwright install chromium`.

## Layout

```
src/app/                 routes: / (chat), /login, /appointments
src/components/chat/     message bubbles, confirmation card, composer, empty state
src/lib/sse.ts           incremental Server-Sent Events parser
src/lib/api.ts           typed API client and event decoding
src/lib/use-chat.ts      the chat state machine
src/lib/ics.ts           RFC 5545 calendar file
tests/                   unit (Vitest) and e2e (Playwright)
```
