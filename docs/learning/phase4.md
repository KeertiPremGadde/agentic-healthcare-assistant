# Phase 4 – MCP tools & integrations: interview Q&A

What we built: clinic operations as an MCP server (8 typed tools), a graph that calls them through
an MCP client, cancellation with human confirmation, an optional Google Calendar step, and a
"real clinics nearby" lookup from OpenStreetMap. Code: `src/medagent/mcp_server/`,
`src/medagent/tools/`, `src/medagent/integrations/`. Decisions: [ADR 0007](../adr/0007-mcp-tools-calendar-and-osm.md).

---

### What is MCP and why use it here?
The Model Context Protocol is an open standard (JSON-RPC over stdio or HTTP) for exposing tools,
resources and prompts to AI applications. A server declares typed tools with input and output
schemas; any client discovers and calls them. For us that means scheduling is a reusable service:
our LangGraph agent, MCP Inspector and Claude Desktop all use the same `book_appointment`, with the
same validation, instead of each re-implementing database access.

### Where does MCP sit in your architecture?
Nodes depend on a `ClinicTools` interface. `LocalClinicTools` calls `ClinicService` in-process;
`MCPClinicTools` calls the MCP server, which wraps the same `ClinicService`. So the logic exists once
and the transport is a setting (`TOOLS_TRANSPORT=mcp|local`). The same graph test suite runs against
local tools, and one test runs the full book-then-cancel flow through a real server subprocess.

### Did the agent get more autonomous because it has tools now?
No, deliberately. The LLM still only classifies and extracts into Pydantic schemas. *Code* decides
which tool to call and when, and `book_appointment` / `cancel_appointment` only run after the human
confirms through `interrupt()`. MCP changed *where* the tools live, not *who* decides.

### What security issues come with exposing tools?
- `book_appointment(patient_id, ...)` is dangerous if anyone can call it. Our server is stdio-only,
  spawned by a trusted process; HTTP exposure needs authentication first (Phase 5/8).
- The patient id comes from the login/config, never from conversation text, so prompt injection
  can't book for someone else.
- Cancelling another patient's appointment returns `not_found`, which doesn't reveal it exists.
- The server subprocess gets only the environment it needs (DB URL, clinic/calendar settings), not
  the LLM API key.
- Never print to stdout in a stdio server: stdout *is* the protocol channel. Logs go to stderr.

### Which MCP pitfalls did you hit?
- **Version skew:** MCP SDK 2.x renamed `FastMCP` to `MCPServer`, but `langchain-mcp-adapters` still
  requires `mcp<2`. I pinned `mcp>=1.30,<2` and told Dependabot to ignore 2.x.
- **Sessions:** the adapter's `get_tools()` without a session spawns a new server process *per tool
  call*. I keep one session open per conversation.
- **anyio task ownership:** the session context manager must be entered and exited in the same task,
  so one long-lived "owner" task holds it while calls run as separate tasks.
- A keyword collision: my helper `_call(name, ...)` clashed with the tool argument `name` (a doctor's
  name). Positional-only parameters (`/`) fixed it.

### Why did you make the graph async, and what broke on Windows?
MCP clients are async and FastAPI (Phase 5) is async, so nodes, runner and checkpointer became async.
Then I measured a Windows-only conflict: psycopg's async mode (the checkpointer) needs a
`SelectorEventLoop`, but spawning subprocesses (the MCP stdio server) needs a `ProactorEventLoop`, and
neither loop supports both. The app runs on a selector loop and the MCP client runs on its own
proactor loop in a background thread, with calls handed over via `run_coroutine_threadsafe`. On Linux
it's just an extra loop. I tested both loops before designing this rather than guessing.

### How does the calendar integration work, and why a service account?
One shared "MedAgent Demo Clinic" calendar written by a service account. It's the simplest thing
that works for an anonymous public demo: no OAuth consent screen, no Google app verification for a
sensitive scope, no per-user tokens. Trade-offs: patients don't get the event in their own calendar,
and service accounts can't invite attendees without Workspace domain-wide delegation. Details I'd
mention:
- **Optional:** no credentials → `NullCalendar`; booking is unchanged. `GOOGLE_CALENDAR_ID=primary` is
  rejected because it's the service account's own invisible calendar (a classic gotcha).
- **Best-effort after the commit:** Google being down never undoes a booking.
- **Idempotent:** the event id is derived from the appointment id, so a retry gets a 409 instead of
  a duplicate; cancelling deletes it.
- **Minimal data:** doctor + confirmation number only, scope `calendar.events` only. The legacy code
  sent the patient's name and email to Google and stored an OAuth token with `pickle`.

### What did you learn from the OpenStreetMap integration?
Public infrastructure has policies and real-world latency:
- Usage policy: identifying User-Agent, ≤1 Nominatim request per second, small queries, backoff on
  429/504, and a 24 h Postgres cache so repeated questions never reach the servers.
- Measured 30–55 s per Overpass query on a busy evening. My 30 s timeout was too short, and my retry
  hit the per-IP rate limit.
- **A timed-out Overpass query returns HTTP 200 with zero results and a `remark`.** Without checking
  it, the bot would have said "no clinics near Hamburg". Now it's an error, and stale cache wins.
- One global result cap cut hospitals out of the answer, because Overpass sorts output by element id,
  not by kind. Per-kind caps fixed it; the cache key is versioned so old payloads aren't served.
- Results are clearly labelled non-bookable, and the ODbL attribution is enforced in code by the
  output guard.

### How did you test all this?
- `ClinicService` rules against Postgres: authorisation, races (partial unique index), cancel rules.
- The MCP server in memory (`create_connected_server_and_client_session`): every tool has an output
  schema, results round-trip into the Pydantic models, and bad input is rejected at the boundary.
- A graph test that books and cancels through a real stdio server subprocess on the test database.
- Calendar with a fake service: no PII in the event, deterministic ids, 409/404 handling, and
  best-effort behaviour (a failing calendar still books).
- OpenStreetMap with `httpx.MockTransport` and a hand-written Overpass fixture: cache hit/expiry,
  stale-on-error, 429 backoff, timeout remark. No network in CI.
- A `scripts/check_calendar.py` self-test against the real calendar that prints only OK or FAILED.

### What would you do next?
Streamable-HTTP transport with OAuth for the MCP server; an outbox for calendar writes; `.ics`
downloads for patients; rescheduling as a single confirmed operation; a self-hosted or mirror
Overpass instance for predictable latency.
