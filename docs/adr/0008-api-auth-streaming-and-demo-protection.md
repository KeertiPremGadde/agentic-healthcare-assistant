# 0008 – API: JWT auth, SSE streaming, per-user isolation and demo cost protection

Status: accepted (Phase 5)

## Context
The graph needs an HTTP API that a browser frontend (Phase 6) and strangers on a public demo can
use. Three things must hold: nobody can act as, or see the data of, another user; the booking
confirmation (human in the loop) works across HTTP requests; and an anonymous public endpoint
that spends real LLM money cannot be turned into a bill.

## Decision

### 1. Accounts and JWT
- **Username + password only**, no email: the public demo collects no personal data (GDPR). Each
  user owns one synthetic `Patient` row; the page says "don't enter real data".
- Passwords: **Argon2id** (`pwdlib`); only the hash is stored. Login does one Argon2 verification
  even for unknown usernames and returns the same 401 for both failures (no user enumeration, no
  timing signal).
- Tokens: **HS256 JWT** with only `sub` (user id), `iat`, `exp`; 60 minutes; no refresh token yet.
  Decoding pins `algorithms=["HS256"]` and requires all three claims, so `alg: none`, other
  algorithms, tampered, expired and claim-less tokens are rejected. OAuth2 password form for
  login, so Swagger's **Authorize** button works.
- `JWT_SECRET` must be 32+ random characters; **the app refuses to start** with the placeholder
  unless `APP_ENV=local`.

### 2. The patient id comes from the token, never from the chat
`token -> user id -> users row -> patient_id -> graph run config`. Request bodies carry no
patient id (extra fields are ignored; tested with a spoofed `patient_id`). Appointments
endpoints use the same derived id, and another user's appointment id answers 404.

### 3. Conversation ids are namespaced per user
The graph thread is `u{user_id}:{conversation_id}`, built server-side. A user cannot address
another user's conversation (IDOR) because it doesn't exist in their namespace: read, resume and
write all behave as 404 / "your own new conversation". Verified by a mutation: removing the
prefix makes the isolation test fail.

### 4. Confirmation over HTTP
`POST /v1/chat` stops with a `confirmation` event (or `pending` in JSON mode) when the graph hits
`interrupt()`; the state is in the Postgres checkpoint, not server memory. `POST
/v1/chat/{id}/resume {"confirmed": bool}` continues it; resuming with nothing pending is 409 (no
double booking), a second message while a turn runs is 409 (per-conversation lock, with a 5 minute
staleness backstop). `GET /v1/chat/{id}` returns history + pending so a reloaded page can restore
the confirmation card.

### 5. SSE protocol
Events: `step` (a node STARTED, via LangGraph `stream_mode="tasks"`, so "Searching..." shows
while it happens), `token`, `confirmation`, `message`, `done` (conversation id, tokens, cost),
`error` (safe code/message). `?stream=false` returns the same as JSON (for /docs and tests).
- **`token` events are a replay.** The reply arrives as one structured-output object, so the
  typing effect is chunks of the finished text (15 ms apart); `step` events are live. True token
  streaming would need streaming the `answer` field of a JSON object: deferred.
- POST + `fetch` stream (EventSource only supports GET). A keepalive comment every 15 s survives
  proxies during slow turns (a cold OpenStreetMap lookup takes up to a minute), `X-Accel-Buffering:
  no` stops nginx from buffering, and the turn runs in a task that is cancelled on disconnect.

### 6. Demo cost protection (all checked BEFORE any LLM call)
| Layer | Default | Notes |
|---|---|---|
| Rate limit per IP: register / login | 5 per hour / 10 per minute | in-memory sliding window |
| Rate limit per user: chat | 20 per minute | |
| Message length | 1,000 characters | |
| Messages per user per UTC day | 50 | counted up front, so failed turns count |
| **Global estimated spend per UTC day** | **$1.00** | sums per-run cost from the cost logging; then HTTP 503 `demo_limit_reached`, no LLM call |
- **Confirmations are free** (no LLM call), so they still work at the limit: a pending booking can
  always be completed or declined.
- **Safety beats limits:** when a limit is reached, the deterministic red-flag rules still run, so
  "I have chest pain" gets the emergency answer (200, no LLM) instead of a limit error.
- The budget is a **tripwire, not a ledger**: concurrent in-flight turns can overshoot by a few
  tenths of a cent, estimates use list prices, and the provider's invoice is the truth. Keep a
  provider-side spend limit as the hard stop.
- Deviation from the plan: a small in-memory rate limiter instead of `slowapi`: ~20 lines,
  deterministic to test, works with streaming responses, no global decorator state. Limits and
  locks assume one process; several instances need Redis / advisory locks (Phase 8).

### 7. Errors, logging, CORS
One envelope `{"error": {"code", "message", "request_id"}}`; messages are user-safe and never
contain exception text. FastAPI's default 422 **echoes the offending input**, which for
`/register` would send the password back, so validation errors return field names and reasons only
(tested). Every response has `X-Request-ID` (a client value is accepted only if it matches a strict
pattern), plus `nosniff` and `no-store`. CORS allows the configured origin only, no credentials
(Bearer header, not cookies: no CSRF surface).

### 8. Windows and uvicorn
Uvicorn on Windows runs the proactor loop, which psycopg's async mode rejects (ADR 0007).
`scripts/serve.py` starts uvicorn with `loop="none"` inside `asyncio.run(..., loop_factory=
SelectorEventLoop)`. Verified against the real stack (MCP subprocess, pooled Postgres
checkpointer, Haiku). Linux/AWS need nothing special.

## Consequences
- A stranger can use the demo but can't read others' data, impersonate a patient, brute-force
  logins quickly, or run up the bill beyond about the daily budget.
- Known limitations: no refresh tokens or logout (60 minute expiry); no account-deletion
  endpoint yet (right to erasure; planned); in-memory limits per process; rate limiting by peer IP
  (behind a proxy, run uvicorn with `--proxy-headers` and a trusted `--forwarded-allow-ips`);
  usernames can be enumerated through registration conflicts.
- Phase 6 decided where the browser stores the token: memory plus `sessionStorage` (ADR 0011).
