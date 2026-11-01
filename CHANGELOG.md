# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow `v0.<phase>.<patch>`.

## [Unreleased]

### Added
- German fixed texts (Phase 7 follow-up): the "I don't know" reply, dose referral, `Quellen:` /
  `Inhalt:` labels and the disclaimer (with the on-call number 116 117) are German for German
  questions, chosen per turn from the router's `language` (`reply_language`); other languages fall
  back to English. The output guard accepts the fixed texts of every language, the frontend reply
  parser understands the German layout, and the dose guard knows German forms (Teelöffel, Zäpfchen,
  Hübe, ...). English output is unchanged byte for byte. Emergency and harmful replies stay English
  until the next PR. ADR 0015.
- Langfuse tracing (Phase 7): one trace per graph turn with nested node, LLM and tool observations,
  token usage, a session per conversation, a hashed user id, and route / kind / estimated cost as
  scores. Optional (no keys: nothing happens), never breaks a turn, covers the API and the dev CLI.
  **Message text, passages, doctor and patient details and ids are redacted before they leave the
  process** (`LANGFUSE_CAPTURE_CONTENT=false`, the default), in two layers: the SDK `mask` hook and an
  export-stage scrubber that also covers exception text (LangGraph's pause for a confirmation put
  the proposal into a status message; found by reading real traces back). Only the SDK's own spans
  are exported. `LANGFUSE_SAMPLE_RATE` limits the share of turns traced.
- Evaluation harness (Phase 7, `src/medagent/evals/`, `scripts/run_evals.py`): frozen golden sets v1.0
  with a hash lock (65 RAG questions incl. 5 German, 100 routing messages, 27 booking scenarios incl.
  isolation and patient-injection cases), pure scorers, a booking judge that decides from database
  state, suites for retrieval, routing, RAG answers and booking, a per-run spend cap, and result files
  with dataset hashes. LLM-judged layer: ragas 0.4.3 and DeepEval 4.3.2 (optional `evals` dependency
  group) with a Haiku judge, one retry and a missing-score gate. `evals/thresholds.yaml` +
  `run_evals.py gate`: exact hard gates for safety (flag recall 100%, false positives 0, dose leaks 0,
  booking hard violations 0) and baseline-minus-margin gates for quality. The Phase 2 baseline is
  committed under `evals/results/baseline-*`. ADR 0013.
- `scripts/check_langfuse.py`, ADR 0012 and the first section of `docs/learning/phase7.md`.
- Contextual chunk headers (Phase 7, RAG improvement 1, kept): every chunk is embedded and full-text
  indexed with `Title (also called: ...)` in front; the stored text and citations are unchanged
  (`kb_chunks.context_header`, `tsv` generated from header + content, migration `a7c1d2e3f405`;
  re-ingest needed, the document hash includes a header version). Measured against the frozen
  baseline: English hit@1 0.900 -> 0.925, hit@5 0.975 -> 1.000, MRR 0.926 -> 0.956 (three questions
  moved up, none down; German unchanged); judged, mean of three runs: context precision 0.867 ->
  0.909 (beats the baseline spread 0.030), faithfulness 0.851 -> 0.879 and context recall 0.956 ->
  0.971 (up, within noise). Safety gates unchanged. Results in `evals/results/headers/`.
- Cross-encoder reranker (Phase 7, RAG improvement 2, kept as the default): `Xenova/ms-marco-MiniLM-L-6-v2`
  via fastembed reorders the top 10 candidates (`RERANKER`, `RERANKER_MODEL`, `RERANKER_TOP_N`;
  `RERANKER=score` restores the old blend). EN hit@1 0.925 -> 0.975, MRR 0.956 -> 0.9875; judged
  context precision 0.909 -> 0.929 (every run above every previous run), faithfulness unchanged.
  Cost: 88 MB on disk, 218 MB resident (416 MB peak), +0.65-0.74 s per question on a laptop CPU.
  German is unchanged (the right topic is not in the candidate pool). Four models compared with
  `scripts/compare_rerankers.py`. ADR 0014, including the Phase 8 notes (bake the model into the
  image, memory per request).
- English search query for German questions (Phase 7, RAG improvement 3, kept): the router also
  returns `language` and `search_query_en` (same call, no extra LLM call); a non-English medical
  question is retrieved with the English query and answered in the user's language with the English
  citation labels. The safety rules and router flags only ever see the user's own text, and English
  messages are always retrieved with their original text (tests, mutation-checked). German in-scope
  set: hit@5 0.4 -> 1.0, answered 1 of 5 -> 5 of 5, English metrics and all hard safety gates
  unchanged. Known gap: the German "I don't know", labels and disclaimer are still English (separate
  PR). New `retrieval-de` eval suite, `de_translation_rate`, `de_answered_in_german_rate`. Pre-commit
  ruff pinned to the locked version (a test keeps them equal). Results in
  `evals/results/query_translation/`.
- `RAG_MIN_SCORE` re-measured (Phase 7, RAG improvement 4): 0.70 confirmed, no change. A locked
  tuning set (`evals/datasets/threshold_dev.json`, 34 items) is used to choose and the golden set to
  confirm; the thresholds 0.691-0.722 behave identically on both, and the rule's pick (0.726) fails
  the golden confirmation. New: `retrieval --dataset threshold_dev`, plateau margins in every
  retrieval run, gate `en_false_abstain_at_threshold <= 0.025`. ADR 0014, `evals/results/threshold/`.

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
