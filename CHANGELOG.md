# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow `v0.<phase>.<patch>`.

## [Unreleased]

### Changed
- Dependabot: ignore minor and major bumps of the Python base image (we run 3.12 everywhere) and
  major bumps of `typescript` (typescript-eslint does not support TypeScript 7 yet).

## [0.6.0] - 2026-11-01

### Added
- Phase 6 frontend (`frontend/`): Next.js App Router, TypeScript, Tailwind, shadcn/ui. Streaming chat
  with live agent steps and source citations, booking and cancel confirmation card (Confirm / Change
  time through the resume endpoint), emergency (red) and crisis-support (calm violet) cards, login
  and registration with the demo notice, "My appointments" with cancel, "Add to calendar" (.ics)
  download, disclaimer banner, example prompts, light and dark themes, mobile layout, keyboard and
  screen-reader support. Token in memory plus `sessionStorage`; one user per tab is enforced.
- The `message` event and `ChatResponse` carry `kind` (`normal` | `booked` | `emergency` |
  `harmful_intent`) and `appointment_id`, so clients don't parse text to decide how to present a reply.
- Tests: Vitest (SSE parser, event decoding, citations, `.ics`) and a Playwright smoke test against a
  mock API; a `frontend` CI job; an npm entry in `dependabot.yml`; `npm run screenshots` and
  `docs/screenshots/`.
- Doctor suggestions as cards (name, specialty, city, languages) with a Book button that sends
  "Book number N"; only the newest list is bookable. The `message` event and `ChatResponse` carry
  `doctors` and `booking` (appointment id, doctor, time) as data, additive, with tests.
- Safety cards: every known phone number is a `tel:` link; "Call 112" button on the emergency card;
  TelefonSeelsorge, 112 and a Giftnotruf (poison control) section with regional numbers and the
  official BfR list on the crisis card.
- Doctor suggestions read as intro, cards, hint, then the not-a-diagnosis note; disabled Book buttons
  explain themselves; the confirmation card shows the assistant's reason when it offers another day.
- Crisis card: numbers on call buttons instead of repeated links in the text. Poison control lists
  only numbers confirmed on the official BfR directory (Berlin, München; "Stand 22.07.2026", checked
  2026-11-01) and links that directory for every other region.
- The booked card is structured like the confirmation card (doctor, time, confirmation number) with
  "Add to calendar" below; a shorter one-line disclaimer strip; a fourth example prompt.
- ADR 0011, `docs/learning/phase6.md`.

## [0.5.2] - 2026-10-31

### Added
- Public holidays: doctors are not bookable on the German public holidays of their own city
  (31 Oct closes Leipzig but not Berlin; München also observes Assumption Day, Nürnberg does not).
  Uses the `holidays` library through a static city table with a completeness test; pure
  availability and validation services take an optional `holiday_on` lookup; new booking error
  `public_holiday`; the tools report `holiday` and `detail`; replies say "Dr. X's practice is closed
  on <date> (<holiday>)" and offer the next free slot. `HOLIDAY_LANGUAGE` (`en_US` | `de`).
- ADR 0010, `docs/learning/public-holidays.md`; `.env.example` now documents `CLINIC_TIMEZONE`,
  `SLOT_MINUTES` and `HOLIDAY_LANGUAGE` (the first two were missing).

## [0.5.1] - 2026-10-31

### Added
- Deterministic `harmful_intent` guardrail (English + German) that runs before any LLM call,
  whatever the question form: lethal doses, how to kill/poison/harm someone, "enough to die",
  methods of suicide. Fixed compassionate reply with no information and crisis resources
  (TelefonSeelsorge, 112, 988, poison control), separate from the emergency message.
- Router `is_harmful` flag as a second layer for phrasings the rules miss.
- Dose guard: medical answers never contain a specific dose or quantity (enforced in
  `answer_question` and in the output guard; referral to doctor or pharmacist).
- Red-team set `evals/redteam/cases.json` (50 cases), `tests/unit/test_redteam.py`,
  `scripts/redteam_report.py` (rules vs router on the real model), ADR 0009.
- "Pending follow-ups" section in the plan; red-team LLM evals added to Phase 7.

### Changed
- When a daily limit or the global budget is reached, harmful-intent messages (like emergencies)
  still get their fixed reply instead of "limit reached".
- Emergency rules also recognise "don't want to live anymore", "better off dead".

### Fixed
- The output guard no longer overwrites the fixed dose referral with "I don't know".

## [0.5.0] - 2026-10-31

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

### Fixed
- Booking on a day the doctor doesn't work (e.g. "tomorrow morning" = Sunday) said "no free morning
  slot on that day"; it now says the doctor doesn't work on that weekday. `check_availability`
  reports `works_on_from_day`.

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
