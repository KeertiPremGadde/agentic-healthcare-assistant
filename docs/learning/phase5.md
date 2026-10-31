# Phase 5 – The API: interview Q&A

What we built: a FastAPI service with JWT login, a chat endpoint that streams progress over SSE,
a resume endpoint for the human-in-the-loop confirmation, per-user isolation, and layered cost
protection for a public demo. Code: `src/medagent/api/`, `src/medagent/main.py`,
`scripts/serve.py`. Decisions: [ADR 0008](../adr/0008-api-auth-streaming-and-demo-protection.md).

---

### How does JWT login work, and what's in your token?
`POST /v1/auth/login` checks the password against an Argon2id hash and returns a signed token
(HS256: header.payload.signature). The payload is just `sub` (user id), `iat` and `exp`. Every
request sends `Authorization: Bearer <token>`; the server recomputes the signature with its secret,
checks the expiry, then loads the user. A tampered or forged token fails the signature check, so
the server needs no session table. Nothing sensitive is in the token (it's readable by anyone who
holds it; it's signed, not encrypted).

### How do you prevent classic JWT mistakes?
- **Pin the algorithm** on decode (`algorithms=["HS256"]`): otherwise `alg: none` tokens, or an
  attacker choosing a weaker algorithm, can slip through. Tests cover `none`, HS512, a wrong
  secret, a flipped signature byte, expiry, and each missing claim.
- **Require `exp`, `sub`, `iat`** so tokens can't be immortal or anonymous.
- **Refuse to start with a weak secret** outside local mode (32+ random characters; the generator
  command is in `.env.example`).
- Re-check the user exists on every request, so a token for a deleted account stops working.
- Honest gaps: no refresh tokens and no revocation; a stolen token is valid for up to 60 minutes.

### Why Argon2, and what's the login timing issue?
Argon2id is memory-hard, which makes GPU cracking of a leaked hash database expensive. The timing
issue: if "unknown user" returned instantly while "wrong password" took 80 ms of hashing, an
attacker could enumerate usernames by response time. Login always performs one verification
(against a dummy hash for unknown users) and returns the identical 401 body for both cases.

### How does the server know which patient is booking?
`token -> user id -> users table -> patient_id -> graph run config`. The chat body has only the
message. Even if a client sends `"patient_id": 1` in the JSON, the extra field is ignored and the
booking uses the token's patient (there's a test with a spoofed body). The LLM never sees or picks
a patient id either, so prompt injection ("book this for patient 7") has nothing to act on.

### What's an IDOR and how did you avoid it here?
Insecure direct object reference: letting a client name an object (a conversation id, an
appointment id) without checking it belongs to them. For appointments, queries are scoped by the
token's patient, and someone else's id returns 404 (not 403, so existence isn't revealed). For
conversations, the graph thread id is `u{user_id}:{conversation_id}`, built on the server, so
another user's id simply doesn't exist in your namespace. I proved the test is meaningful by
deleting the prefix (mutation test): Bob could read Alice's conversation and the test failed.

### How does the human-in-the-loop confirmation work over HTTP?
HTTP is request/response, so the pause is split in two requests. The first `POST /v1/chat` runs the
graph until `interrupt()`; the state is saved in the Postgres checkpoint and the response carries a
`confirmation` event. `POST /v1/chat/{id}/resume {"confirmed": true}` loads the checkpoint and
continues. Because the pause lives in the database, not server memory, it survives restarts and
works across several workers. Guards: resuming with nothing pending is 409 (no double booking), and
`GET /v1/chat/{id}` returns the pending question so a reloaded page can show the card again.

### What is SSE and why not WebSockets?
Server-Sent Events: a normal HTTP response that stays open and sends `event:`/`data:` text blocks.
It's one-directional (server to client), which is all chat streaming needs, works through ordinary
proxies, and reconnects are simple. WebSockets are bidirectional and need their own handshake,
auth story and infrastructure support. One catch: browsers' `EventSource` only supports GET, so we
POST and read the body with `fetch` and a stream reader (what the Vercel AI SDK does).

### What do your streamed events mean, and what's honest about "streaming"?
`step` (a graph node started, from LangGraph's `tasks` stream mode, so "Searching the knowledge
base…" appears while it runs), `token`, `confirmation`, `message`, `done`, `error`. **The token
events are a replay:** the answer comes back from structured output as one complete JSON object, so
there is nothing to stream token by token. I replay the finished text in 3-word chunks 15 ms apart
for the typing effect. Step events are live. Real streaming would mean streaming the `answer` field
inside the JSON. I'd say this plainly in an interview.

### What can go wrong with a long-lived stream, and how do you handle it?
- **Idle timeouts at proxies:** a keepalive comment line every 15 s (a cold OpenStreetMap lookup
  takes up to a minute), plus `X-Accel-Buffering: no` so nginx doesn't buffer the stream.
- **Client disconnects:** the turn runs in its own task, cancelled when the connection drops; the
  database write inside a tool call is a single atomic transaction, so a cancel can't half-book.
- **Stuck state:** one running turn per conversation (409 otherwise), with a lock that expires
  after 5 minutes in case a stream is abandoned before its cleanup runs.
- **Metering failed runs:** a failed LLM call can still be billed, so cost is recorded in a
  `finally`, exactly once (tested with a model that raises).

### How do you protect a public demo that spends real money?
Layers, all checked before any LLM call: per-IP limits on register and login, a per-user chat rate,
a 1,000-character message cap, 50 messages per user per day, and a **global daily budget** ($1.00)
summed over every user's recorded cost; past it, chat returns 503 "demo limit reached" and makes no
LLM call. Anyone can register many accounts, which is exactly why the global cap exists: per-user
limits alone don't bound the total. I verified it live: with a tiny budget the spend and message
count did not change after blocked requests.

### Why do confirmations and emergencies bypass the limits?
Confirming a booking costs no LLM call, and blocking it would strand a user with a half-finished
booking, so `resume` is exempt. Emergencies are a safety question: the deterministic red-flag rules
need no LLM, so "I have crushing chest pain" still gets the emergency answer when the budget is
gone, instead of "come back tomorrow". Both are tested, including with the German phrasing.

### What are the limits of that budget guard?
It's a tripwire, not a ledger: concurrent turns in flight can overshoot by a few tenths of a cent,
costs are estimates from list prices, and the counter is per UTC day. The provider's invoice is the
truth, so a provider-side spend limit remains the hard stop. I'd mention that in a security review.

### What bug did you find in FastAPI's defaults?
The default 422 validation response echoes the offending `input`. For `/register`, a too-short
password would be sent straight back in the response (and into any proxy log). I replaced the
handler so it returns field names and reasons only, and a test asserts the password never appears.

### Why your own rate limiter instead of slowapi?
~20 lines (a sliding window per key), deterministic to test with an injected clock, works with
streaming responses and as plain dependencies, and has no global decorator state. The trade-off is
that it's per process: several instances would each count separately, so Phase 8 would move it to
Redis. I stated that deviation in the ADR rather than hiding it.

### Why username-only registration?
A public demo shouldn't collect personal data it doesn't need. No email means nothing to leak, no
verification flow, and nothing to erase beyond a pseudonymous username. The cost: no password reset
(acceptable for a demo) and no way to contact users. An account-deletion endpoint (right to erasure)
is a known gap I'd add next.

### What did live testing show that unit tests wouldn't?
I ran the real server on Windows (selector loop, MCP subprocess, pooled Postgres checkpointer,
Haiku) and drove it with curl: register, login, SSE chat, booking with confirmation (the event
landed in the real calendar), double-confirm refused, a second user denied on every route, budget
cap enforced. The metering matched my own per-turn numbers ($0.000723 for four messages). It also
showed my first timing measurement was wrong (my timing script was the slow part: the stream took
1.6 s in total), which is why I re-measured before drawing a conclusion.

### How do you test an authenticated, streaming API without a browser?
`httpx.AsyncClient` over an ASGI transport talks to the app in-process: real routing, middleware,
auth, Postgres and graph; fake LLM and in-memory checkpointer. SSE responses are parsed from the
body into `(event, data)` pairs, so tests assert event order, that the replayed tokens concatenate
to the final message, keepalives under a slow model, and that an abandoned stream frees its lock.

### What would you do next?
Refresh tokens and logout; account deletion; real token streaming; Redis for limits and locks;
`--proxy-headers` plus a trusted proxy list for real client IPs; an outbox for calendar writes; and
OpenTelemetry/Langfuse traces keyed by the request id (Phase 7).
