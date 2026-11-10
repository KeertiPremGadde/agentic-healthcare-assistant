# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Design decisions are in [docs/adr](docs/adr).

## [Unreleased]

### Added
- Evaluation harness with frozen golden sets, DB-state judging for bookings and exact safety gates (ADR 0013).
- Red-team evals that run the whole bot: 195 cases across 11 attack groups, with a known-gaps list (ADR 0020).
  Final run: all cases pass, no dose, prompt or tool-call leaks (ADR 0027).
- Eval gate in CI: a free check on every PR and a capped paid run when the agent, guardrails, RAG or evals
  change (ADR 0028).
- Langfuse tracing, with message content redacted by default (ADR 0012).
- RAG improvements, each measured against the baseline: contextual chunk headers, a cross-encoder
  reranker and an English search query for German questions (ADR 0014).
- German versions of the fixed replies (disclaimer, "I don't know", dose referral, emergency and crisis
  replies) (ADRs 0015, 0016).
- Supportive reply for non-acute self-harm and passive suicidal thoughts, separate from the emergency
  reply (ADRs 0021, 0023, 0024).
- Character normalisation before the safety rules, so spellings like "k1ll" or zero-width characters
  don't slip past them (ADR 0026).

### Changed
- Safety rules cover more vocabulary and German inflected forms (ADRs 0017, 0018).
- General questions about a red-flag topic ("what are the signs of a stroke?") get an answer with a
  safety notice instead of the emergency reply (ADR 0019).
- The dose guard also catches amounts per kg, per day and in grams (ADR 0022).
- Routing dataset v1.1 with flag-only scoring (ADR 0025).

### Fixed
- If the router call fails, the user gets a neutral reply with the emergency and crisis numbers instead
  of a generic apology.

## [0.6.0] - 2026-11-01

### Added
- Next.js frontend: streaming chat, doctor cards with a Book button, booking confirmation card,
  `.ics` calendar download, emergency and crisis cards with call buttons, light and dark mode (ADR 0011).
- Vitest unit tests and a Playwright smoke test.

## [0.5.2] - 2026-10-31

### Added
- Doctors can't be booked on the public holidays of their city (ADR 0010).

## [0.5.1] - 2026-10-31

### Added
- Rule-based harmful-intent guardrail (English and German) that runs before any LLM call, plus a router
  flag as a second layer (ADR 0009).
- Dose guard: medical answers never contain a specific dose.
- First red-team set (50 cases).

### Fixed
- The output guard no longer replaces the dose referral with "I don't know".

## [0.5.0] - 2026-10-31

### Added
- HTTP API: SSE chat, booking confirmation endpoint, appointments, health checks (ADR 0008).
- JWT auth with Argon2id passwords.
- Demo cost protection: rate limits, a daily per-user message limit and a global daily budget.

### Fixed
- Asking for a slot on a day the doctor doesn't work now says so, instead of "no free slot that day".

## [0.4.0] - 2026-10-31

### Added
- MCP server with the clinic tools (availability, booking, cancellation, calendar) (ADR 0007).
- Cancellation with a confirmation step.
- Optional Google Calendar sync.
- Nearby clinics from OpenStreetMap, cached for 24 hours.

### Changed
- The graph, runner and checkpointer are async.

## [0.3.0] - 2026-10-31

### Added
- LangGraph multi-agent graph: guardrail, supervisor, medical RAG, doctor finder and booking agents (ADR 0006).
- Human-in-the-loop booking with `interrupt()`, re-validated before the insert.
- Rule-based emergency detection (English and German) before any LLM call.
- Token and cost logging per run, without message text.
- CLI chat for local testing.

## [0.2.0] - 2026-10-31

### Added
- RAG knowledge base on pgvector: hybrid search (vector and full text), reranking, citations (ADR 0005).
- MedlinePlus health topics as the public corpus.

## [0.1.0] - 2026-10-31

### Added
- Project setup: uv, ruff, mypy, pytest, pre-commit, Docker Compose, CI.
- Data layer: SQLAlchemy models for doctors, schedules, patients and appointments, Alembic migrations,
  and a seed with 100 synthetic doctors (ADR 0004).
