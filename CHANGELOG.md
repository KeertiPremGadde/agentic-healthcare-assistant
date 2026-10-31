# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow `v0.<phase>.<patch>`.

## [Unreleased]

### Added
- Phase 5 HTTP API: `POST /v1/chat` (SSE with live `step` events, replayed `token` chunks,
  `confirmation`, `done`; `?stream=false` for JSON), `POST /v1/chat/{id}/resume`,
  `GET /v1/chat/{id}`, `GET /v1/limits`, `GET/DELETE /v1/appointments`, `/ready`.
- JWT login (Argon2id passwords, HS256, pinned algorithm, required claims), username-only demo
  accounts, `users` and `daily_usage` tables; the patient id comes from the token, conversation ids
  are namespaced per user.
- Demo cost protection: per-IP register/login limits, per-user chat rate, 1,000-character
  messages, 50 messages/user/day, and a global daily budget (`DAILY_BUDGET_USD`, default $1.00)
  with no LLM call once reached; confirmations and emergency answers still work at the limit.
- Request IDs, a single error envelope (validation errors never echo input), security headers,
  CORS without credentials, OpenAPI docs, `/demo` page (local mode), `scripts/serve.py`.
- Runner: `stream_turn` yields live step events (LangGraph `tasks` mode) and meters cost exactly
  once even when a run fails; `run_turn` consumes it. Pooled async Postgres checkpointer.
- `GET /` redirects to `/docs` and `GET /favicon.ico` returns 204, so the bare URL shows no 404.
- ADR 0008, `docs/learning/phase5.md`; settings `JWT_SECRET`, `JWT_EXPIRE_MINUTES`,
  `MAX_MESSAGE_CHARS`, `DAILY_MESSAGE_LIMIT`, `DAILY_BUDGET_USD`, `*_RATE_*`.

### Changed
- The app refuses to start with the placeholder or a short `JWT_SECRET` unless `APP_ENV=local`.

## [0.4.0] - 2026-10-31

### Added
- Phase 4 MCP clinic server (`python -m medagent.mcp_server`, FastMCP, 8 typed tools) and an MCP
  client (`langchain-mcp-adapters`, one persistent stdio session); `ClinicService` holds the logic
  once, `ClinicTools` interface with local and MCP implementations (`TOOLS_TRANSPORT`).
- Cancellation flow with `interrupt()` confirmation (own, future, booked appointments only).
- Optional Google Calendar integration: service account + one shared demo calendar, best-effort
  after commit, idempotent event ids, no patient data; `scripts/check_calendar.py`;
  `appointments.calendar_event_id`.
- `find_nearby_clinics` from OpenStreetMap (Nominatim + Overpass), 24 h Postgres cache
  (`external_cache`), ODbL attribution, never bookable; router routes `cancel` and `nearby_clinics`.
- ADR 0007, `docs/learning/phase4.md`; settings `TOOLS_TRANSPORT`, `GOOGLE_SERVICE_ACCOUNT_FILE`,
  `GOOGLE_CALENDAR_ID`, `OVERPASS_URL`; `pytest -m llm` prints total tokens and cost.

### Changed
- The graph, runner and checkpointer are async (`AsyncPostgresSaver`); on Windows the MCP client
  runs on its own proactor loop (`core/aio.py`).
- Dependabot ignores `mcp>=2` until `langchain-mcp-adapters` supports it.

### Fixed
- The LLM cost report no longer prints during `-m "not llm"` runs.

## [0.3.0] - 2026-10-31

### Added
- Phase 3 multi-agent graph (LangGraph): guardrail → supervisor → medical_rag / doctor_finder /
  booking / respond → output_guard, compiled with a Postgres checkpointer (memory per `thread_id`
  survives restarts, including a booking waiting for confirmation).
- Human-in-the-loop booking: `interrupt()` confirmation, re-validation before insert, lost races
  re-confirm the next free slot; patient id from config only.
- Deterministic emergency red-flag rules (English + German) before any LLM call, router
  `is_emergency` as second layer, safety notice for general questions about emergencies.
- Per-run token usage and estimated USD cost logged as JSON (pseudonymised ids, no message text);
  `observability/cost.py` price table.
- CLI chat `python -m medagent.agents.chat --patient <email> [--thread ...] [--verbose]`;
  `scripts/export_graph.py`; ADR 0006; `docs/learning/phase3.md`.
- Shared `Specialty` enum used by the seed and the router.

### Changed
- Structured output uses `method="json_schema"` (Claude Sonnet 5.5 rejects forced tool calls); RAG
  answer `max_tokens` raised to 4096 to leave room for thinking.

### Fixed
- Alembic autogenerate no longer proposes dropping LangGraph's checkpointer tables
  (`include_name` filter + `alembic check` test).

## [0.2.0] - 2026-10-31

### Added
- Phase 2 RAG knowledge base: `kb_documents` / `kb_chunks` tables (pgvector HNSW, generated
  `tsvector` + GIN, `vector(384)`) with a licence, attribution and `is_public` flag per document;
  `Embedder` interface with local FastEmbed (`BAAI/bge-small-en-v1.5`, no API key); source-agnostic,
  idempotent ingestion (PDF and MedlinePlus XML loaders); hybrid retrieval (vector + full-text, RRF,
  `ScoreReranker` behind a `Reranker` interface); cited answers via Anthropic structured output with
  disclaimer and "I don't know" paths; CLIs `python -m medagent.rag.ingest` / `medagent.rag.ask`.
- Public corpus: MedlinePlus Health Topics (US public domain, attributed in citations and README),
  with a guard that excludes third-party copyrighted topics. `Medical_book.pdf` is local-only
  (`KB_PUBLIC_ONLY`). NHS Health A-Z deliberately not ingested (ADR 0005).
- ADR 0005; `scripts/fetch_medlineplus.py`; settings `EMBEDDING_PROVIDER`, `EMBEDDING_DIM`,
  `KB_PUBLIC_ONLY`, `RAG_MIN_SCORE`, `ANTHROPIC_API_KEY`; CI caches the FastEmbed model.
- Tests: chunking, fusion/rerank, loaders (incl. hand-built PDF), answer logic, Postgres integration
  (idempotent ingest, hybrid search, public-only filter), real-model test, `llm`-marked Claude tests
  (run only with `-m llm`).

### Changed
- Default LLM is Anthropic `claude-haiku-5-5` (`LLM_PROVIDER=anthropic`); use `claude-sonnet-5-5` for demos.
- Dependabot ignores Python image versions >= 3.14 (project supports 3.12-3.13).

### Fixed
- `API_CORS_ORIGINS` in `.env` failed to parse (pydantic expects JSON for `list[str]`); it now accepts
  comma-separated values or JSON.
- Alembic template imports `pgvector.sqlalchemy` so autogenerated vector migrations run.

## [0.1.0] - 2026-10-31

### Added
- Phase 0 foundation: project layout, uv/ruff/mypy/pytest, FastAPI `/health`, docker-compose
  (Postgres + pgvector), Dockerfile, CI/CD workflows, docs (plan, architecture diagrams, ADRs).
- Phase 1 data layer: SQLAlchemy 2.0 models (Doctor, DoctorSchedule, Patient, Appointment),
  Alembic initial migration (enables `vector` extension), idempotent synthetic seed
  (`scripts/seed.py`), pure timezone-aware `availability`/`validation` services, thin repository,
  `CLINIC_TIMEZONE` / `SLOT_MINUTES` settings, unit + integration tests, `docs/learning/phase1.md`.
- Deterministic Faker (`de_DE`) seed: 100 synthetic doctors across 19 specialties and 10 German
  cities, with varied weekly schedules and spoken languages; `Doctor.city` / `Doctor.languages`
  (second migration); `get_doctors` filters by specialty, city and language. Faker is a runtime
  dependency so the seed also works when deployed.
- Plan: Phase 4 gets an OpenStreetMap Overpass "find nearby clinics" tool (ODbL, usage policy, cache,
  separate from bookable doctors).
