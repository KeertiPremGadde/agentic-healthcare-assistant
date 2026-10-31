# 0007 – Clinic tools behind MCP, async graph, optional calendar, OpenStreetMap lookups

Status: accepted (Phase 4)

## Context
Phase 3 nodes called the database directly. We want clinic operations as a reusable,
self-describing service (usable by our graph, MCP Inspector, Claude Desktop), a calendar entry
for bookings, and a "real clinics nearby" lookup, without weakening the safety properties of
Phase 3 (human confirmation, patient from login, DB-enforced uniqueness).

## Decision

### 1. One `ClinicService`, exposed as MCP tools; nodes depend on a `ClinicTools` interface
- `ClinicService` (sync) holds the logic once: search, availability, slot check, book (re-validate,
  insert, calendar), list, cancel (own, future, booked only), nearby clinics.
- The MCP server (`mcp_server/server.py`, FastMCP) wraps it as 8 typed tools with JSON output
  schemas. `MCPClinicTools` calls them through `langchain-mcp-adapters` over stdio;
  `LocalClinicTools` calls the service in-process (unit tests, `TOOLS_TRANSPORT=local`).
- Human-in-the-loop stays in the graph: `book_appointment` / `cancel_appointment` are only called
  after `interrupt()` confirmation. The tool never decides on its own.
- **Trust boundary:** stdio only, spawned by a trusted local process. Booking/cancelling tools take
  a `patient_id` the caller must have authenticated, so exposing the server over HTTP requires
  authentication first (Phase 5/8). The subprocess gets an explicit environment with only what it
  needs (DB URL, clinic and calendar settings), not the LLM key. Cancelling someone else's
  appointment returns `not_found`, so the tool doesn't reveal that it exists.
- One persistent MCP session per conversation: `get_tools()` without a session would spawn a new
  server process for every tool call.

### 2. Version pin: `mcp>=1.30,<2`
MCP SDK 2.x renamed `FastMCP` to `MCPServer`, but `langchain-mcp-adapters` 0.3.2 requires
`mcp<2`. 1.30 (Sept 2026) is maintained. Dependabot ignores `mcp>=2` until the adapter supports it.

### 3. The graph is async; on Windows the MCP client runs on its own loop
MCP client tools are async, and Phase 5 (FastAPI) needs async anyway: nodes, runner and the
checkpointer (`AsyncPostgresSaver`) are async. Measured on Windows: psycopg's async mode needs a
`SelectorEventLoop`, subprocesses need a `ProactorEventLoop`, and neither loop does both. The app
runs on a selector loop (`core/aio.py`); `MCPClinicTools` runs the MCP session on a proactor loop in
a background thread, handing calls over with `run_coroutine_threadsafe`. The session is owned by
one long-lived task because anyio requires entering and exiting it in the same task. On Linux
(CI, Docker, AWS) it's simply a second loop.

### 4. Google Calendar: service account + one shared demo calendar, optional and best-effort
- Simplest setup that works for an anonymous public demo: no OAuth consent screen or app
  verification, no per-user tokens. Trade-off: patients don't get the event in their own calendar
  and a service account can't invite attendees without Workspace domain-wide delegation (an
  `.ics` download is the Phase 6 alternative).
- Optional: without `GOOGLE_SERVICE_ACCOUNT_FILE` + `GOOGLE_CALENDAR_ID` (or with
  `GOOGLE_CALENDAR_ID=primary`, the service account's own invisible calendar) a `NullCalendar` is
  used and booking is unchanged.
- Best-effort after the DB commit: a calendar failure never undoes a booking (logged by error
  type; an outbox with retries is the later improvement). Idempotent: event id derived from the
  appointment id, 409 on retry counts as success; cancel deletes it (404/410 count as deleted).
- Least privilege and minimal data: `calendar.events` scope; the event has the doctor and the
  confirmation number, never patient name, email or symptoms. The key file lives in `secrets/`
  (git-ignored; gitleaks + private-key hooks).

### 5. Nearby clinics from OpenStreetMap, never bookable
- Nominatim (geocode, ≤1 req/s, identifying User-Agent) + Overpass, cached 24 h in Postgres
  (`external_cache`), stale cache served if the upstream fails. Results carry the ODbL attribution
  (enforced again by the output guard) and `bookable: false`.
- Measured on the public instance: 30–55 s per query under load, and a timed-out query returns
  HTTP 200 with zero elements plus a `remark`. So: bounding-box queries with exact tag matches
  (index-friendly), one capped `out` per kind (a single global cap cut hospitals out, because
  Overpass sorts by element id), a 60 s read timeout, remark detection (a timeout is an error, not
  "no clinics"), a versioned cache key, and a configurable `OVERPASS_URL` for a mirror or a
  self-hosted instance.

## Consequences
- Tools are reusable outside the graph and testable through the real protocol.
- Two transports to keep in sync: `ClinicTools` is the contract, and the same graph tests run
  against both local and MCP tools.
- Windows-specific loop handling lives in one module; Linux deployments are unaffected.
- The nearby-clinics answer can take up to a minute when it's not cached; acceptable for an optional
  feature, and the reason a mirror/self-hosted Overpass is configurable.
