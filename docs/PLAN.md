# MedAgent – Delivery Plan

> Single source of truth for the build. Work **one phase at a time**, on a feature branch, and
> open one PR per phase. Tick the boxes as you go and add a line to `CHANGELOG.md`.

**Goal:** a production-style **agentic AI healthcare assistant** that answers medical questions
from a curated knowledge base (with citations), routes symptoms to the right specialist, and
books appointments through tool-calling agents with human-in-the-loop confirmation, deployed
live on AWS with CI/CD, evaluations and observability.

**Disclaimer built into the product:** informational only, not a diagnosis; emergencies are
redirected to emergency services. Only synthetic patient data is ever stored.

---

## Tech stack

| Layer | Choice | Replaces (legacy project) |
|---|---|---|
| Agent orchestration | **LangGraph** (StateGraph, supervisor + sub-agents, `interrupt()` HITL, Postgres checkpointer) | `AgentExecutor`, `ConversationBufferMemory`, keyword/BART intent |
| LLM | OpenAI or Anthropic via `init_chat_model`, **structured output** (Pydantic) | Raw prompt strings + string matching |
| Tools | Typed LangChain tools, exposed also as an **MCP server** | Functions called inline in Flask |
| RAG | **pgvector**, hybrid search (vector + Postgres full-text), reranker, citations | Pinecone + MiniLM similarity only |
| API | **FastAPI** async, SSE streaming, JWT auth, rate limiting | Flask sync |
| Data | **PostgreSQL 16**, SQLAlchemy 2.0, **Alembic** migrations | SQLite + `create_all` |
| Frontend | **Next.js** (App Router) + Vercel AI SDK + Tailwind/shadcn | Jinja HTML template |
| Observability | **Langfuse** (or LangSmith) traces, structlog JSON logs | `print()` |
| Evaluation | **RAGAS** (RAG), **DeepEval** (agent/task), pytest | Manual RAGAS run |
| Safety | Emergency triage, PII masking, disclaimer, grounding check | None |
| Packaging | **uv**, `pyproject.toml`, ruff, mypy, pre-commit, gitleaks | pip + unpinned requirements |
| Delivery | Docker, GitHub Actions CI/CD, **Terraform**, AWS ECR + ECS Fargate (or App Runner) | Manual Docker + basic workflow |

### Legacy code to reuse (read, then port, don't copy blindly)

- `D:\medical-chatbot-langgraph\models\*.py` → `src/medagent/db/models/` (doctor, patient, appointment)
- `D:\medical-chatbot-langgraph\models\seed.py` → `scripts/seed.py`
- `D:\medical-chatbot-langgraph\services\availability_service.py`, `validation_service.py` → `src/medagent/services/`
- `D:\medical-chatbot-langgraph\services\doctor_service.py` → specialty routing becomes a structured-output tool
- `D:\Build-a-Complete-Medical-Chatbot-with-LLMs-LangChain-Pinecone-Flask-AWS\src\prompt.py`, `src\helper.py` → RAG prompt + PDF loading ideas
- `…-AWS\calendar_helper.py` → Phase 4 Google Calendar tool
- `…-AWS\evaluation\*` → Phase 7 eval scripts and the existing `testset.csv`
- `…-AWS\data\*.pdf` → `data/raw/` (git-ignored)

---

## Git workflow

- `main` is always green and deployable. Work on `feat/<phase>-<topic>` branches.
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`.
- One PR per phase using `.github/pull_request_template.md`; CI must pass before merge.
- Tag releases `v0.<phase>.0` at the end of each phase.

## Definition of Done (every phase)

- [ ] `uv run ruff check . && uv run ruff format --check .` clean
- [ ] `uv run mypy src` clean
- [ ] `uv run pytest` green, new code has tests
- [ ] Docs updated (README section, this plan's checkboxes, ADR if a decision was made)
- [ ] No secrets, no real patient data committed

---

## Phase 0 – Foundation ✅ (scaffolded)

- [x] Repo layout, `pyproject.toml` (uv), ruff/mypy/pytest config
- [x] `.gitignore`, `.gitattributes`, `.editorconfig`, `.env.example`, pre-commit (+ gitleaks)
- [x] FastAPI skeleton with `/health` + test
- [x] docker-compose (Postgres + pgvector), API Dockerfile
- [x] GitHub Actions CI, Dependabot, PR/issue templates, CODEOWNERS
- [x] Docs: README, PLAN, ARCHITECTURE (diagrams), SETUP, ADRs, CLAUDE.md
- [x] `uv sync`, `pre-commit install`, first commit, create GitHub repo, push
- [x] Put your GitHub username in `.github/CODEOWNERS`
- [ ] Enable branch protection on `main` (require CI) – in GitHub settings, after CI has run once

## Phase 1 – Data layer ✅

- [x] Add deps: `sqlalchemy>=2`, `psycopg[binary]`, `alembic`, `pgvector`
- [x] `db/session.py` (engine + session dependency), port models with typed `Mapped[]` columns
- [x] Appointment: *partial* unique index on `(doctor_id, start_time) WHERE status='booked'` (cancelled slots can be rebooked), `status` enum + CHECK, timestamps
- [x] `DoctorSchedule` model (weekday, start, end in clinic timezone, `Europe/Berlin` via settings); all stored times UTC
- [x] Alembic init + first migration; `scripts/seed.py` (doctors, weekly schedules, synthetic patients)
- [x] Seed expanded with Faker (`de_DE`, fixed seed): 100 doctors, 19 specialties, cities, languages, varied schedules
- [x] Port `availability_service` + `validation_service` as pure functions (timezone-aware)
- [x] Unit tests for slot generation/validation; integration test against Docker Postgres
- **Done when:** `docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py` works and tests pass.

## Phase 2 – RAG knowledge base ✅

- [x] Add deps: `langchain-core`, `langchain-anthropic`, `langchain-text-splitters`, `pypdf`, `fastembed`, `defusedxml`
  (`langchain-postgres` dropped: hybrid search + RRF needs hand-written SQL; chat is Anthropic, embeddings are local)
- [x] Embeddings behind an `Embedder` interface; local FastEmbed `BAAI/bge-small-en-v1.5` (384 dims),
  `EMBEDDING_PROVIDER` setting, model cached in CI, fake embeddings in unit tests
- [x] `kb_documents` / `kb_chunks` tables (HNSW index, generated `tsvector` + GIN, `vector(384)`), licence + attribution + `is_public` per document
- [x] `rag/ingest.py`: source-agnostic loaders (PDF, MedlinePlus XML) → chunk (~1200 chars, bge-small's 512-token limit) → metadata (source, page) → embed → pgvector; idempotent by content hash
- [x] `rag/retriever.py`: hybrid search (vector + `tsvector`, OR semantics) with reciprocal-rank fusion, then `ScoreReranker` behind a `Reranker` interface
- [x] Answers include citations (`[source p.N]` / `[MedlinePlus: Topic]`), disclaimer, and "I don't know" when context is weak (no LLM call) or the LLM says it is insufficient
- [x] Corpus: **MedlinePlus Health Topics** for the public demo (public domain, attributed); `Medical_book.pdf` local dev only (`is_public=false`, `KB_PUBLIC_ONLY`); third-party-copyright guard; **NHS Health A-Z not ingested** (ADR 0005)
- [x] Tests with a tiny fixture corpus (fake embedder), real-model and real-LLM tests behind markers
- **Done when:** `uv run python -m medagent.rag.ingest medlineplus` loads the topics and `uv run python -m medagent.rag.ask "..."` returns a cited answer.
- Later upgrades: local **cross-encoder** reranker (same interface); NHS content only if NHS England confirms AI use in writing *and* a 7-day refresh job exists; re-calibrate `RAG_MIN_SCORE` if the embedding model changes.

## Phase 3 – Multi-agent graph (core of the project) ✅

- [x] Add deps: `langgraph`, `langgraph-checkpoint-postgres`
- [x] `agents/state.py`: typed state with `messages` (add_messages reducer) + booking slots (doctor options, proposal)
- [x] `guardrails/`: deterministic emergency red-flag rules (English + German) before any LLM call, LLM `is_emergency` flag as second layer, general questions answered with a safety notice; PII masking + pseudonymised ids for logs. Scope check is a router route (`out_of_scope`)
- [x] `agents/nodes/supervisor.py`: structured-output router → `medical_rag | doctor_finder | booking | respond` (`json_schema` method, works on Sonnet 5.5 too; low effort)
- [x] `doctor_finder`: specialty as a Pydantic enum (`schemas/specialty.py`, shared with the seed), city/language filters relaxed if unmatched
- [x] `booking`: extracts doctor/date/time from natural language, finds a valid slot, **`interrupt()` for confirmation**, re-validates and books (unique index decides races; a lost slot re-confirms the next one). Patient comes from config, never from the model
- [x] Output guard: disclaimer, uncited medical text blocked, doctor-suggestion note, safety notice
- [x] `agents/graph.py`: compile with Postgres checkpointer (`setup()` owns its tables, Alembic ignores them); graph exported to `docs/diagrams/agent_graph.md`
- [x] Tests: router decisions with a fake LLM, booking happy path + conflict + past date + no + missing patient, restart-and-resume against Postgres, `alembic check` guard; `llm`-marked Haiku tests
- [x] Per-run token usage + estimated cost logged (no PII); CLI chat `python -m medagent.agents.chat`
- **Done when:** a CLI chat can answer a question, recommend a cardiologist and book a slot with confirmation, and memory survives restart. *(Verified with the real CLI in two separate processes.)*
- Later: query rewriting for follow-ups, cancel/reschedule, negation handling + more languages in red-flag rules.

## Phase 4 – Tools & integrations (MCP) ✅

- [x] `mcp_server/`: `search_doctors`, `get_doctor`, `check_availability`, `check_slot`, `book_appointment`, `list_appointments`, `cancel_appointment`, `find_nearby_clinics` via the official MCP Python SDK (`mcp>=1.30,<2`, FastMCP), typed output schemas, stdio only
- [x] Agents load tools through the MCP client adapter (`langchain-mcp-adapters`, one persistent session); `ClinicTools` interface with local + MCP implementations (`TOOLS_TRANSPORT`)
- [x] Graph made async (`AsyncPostgresSaver`); Windows selector/proactor loop split for psycopg async + MCP subprocess (ADR 0007)
- [x] Cancellation with `interrupt()` confirmation; own future appointments only
- [x] Google Calendar event on booking, removed on cancel: service account + one shared demo calendar, optional (`NullCalendar`), best-effort after commit, idempotent event ids, no patient data; `scripts/check_calendar.py`
- [ ] Confirmation email (Resend/SES) – deferred to Phase 8 (SES)
- [x] **`find_nearby_clinics` tool (OpenStreetMap)**, separate from the bookable demo doctors: `bookable: false`, ODbL attribution in tool output and enforced by the output guard, Nominatim ≤1 req/s + identifying User-Agent, bounding-box Overpass query with per-kind caps, 429/504 backoff, timeout-remark detection, 24 h Postgres cache with stale-on-error, configurable `OVERPASS_URL`; tests with a fixture and `httpx.MockTransport` (no network in CI)
- **Done when:** the MCP server works in MCP Inspector and the graph books through it, and the nearby-clinics tool returns attributed, cached results that are clearly labelled non-bookable. *(Graph books and cancels through the MCP server over stdio in tests and the live CLI; real calendar event created and removed; live OSM lookup cached. Inspector: `uv run mcp dev src/medagent/mcp_server/server.py`.)*
- Later: streamable-HTTP transport with auth, calendar outbox/retries, `.ics` download, mirror/self-hosted Overpass.

## Phase 5 – API ✅

- [x] `POST /v1/chat` streaming via SSE (`step` events as nodes start, replayed `token` chunks, `confirmation`, `message`, `done`, `error`; keepalives), `?stream=false` JSON mode; conversation id per conversation, namespaced per user
- [x] `POST /v1/chat/{id}/resume` for HITL confirmation (409 if nothing pending); `GET /v1/chat/{id}` history + pending; `GET /v1/limits`
- [x] `GET /v1/appointments`, `DELETE` to cancel (own only; 404 for others')
- [x] JWT auth (register/login, Argon2 hashes, OAuth2 form so `/docs` Authorize works), username-only accounts (no PII), patient id from the token
- [x] Rate limiting (per IP on register/login, per user on chat), request IDs, one error envelope (no input echoed), CORS without credentials
- [x] **Cost protection:** 1,000-char messages, 50 messages/user/day, **global daily budget (`DAILY_BUDGET_USD`)** from recorded spend; confirmations and emergencies still work at the limit
- [x] OpenAPI documented (tags, response models, error models, security scheme); `/demo` page (local mode); `scripts/serve.py` (Windows selector loop)
- [x] API tests with httpx (auth attacks, isolation, SSE, confirmation round trip, limits, budget), plus mutation checks of the isolation and budget tests
- **Done when:** the full flow works from `/docs` (Swagger) and with `curl`. *(Verified live on Windows with the real server, MCP, Postgres checkpointer and Haiku: register, login, SSE chat, booking with confirmation, cancel, second user denied, budget cap.)*
- Later: refresh tokens + logout, account deletion (erasure), real token streaming, Redis-backed limits/locks, `--proxy-headers` behind a load balancer.

## Phase 6 – Frontend

- [ ] `frontend/`: Next.js + TypeScript + Tailwind + shadcn/ui, Vercel AI SDK `useChat`
- [ ] Streaming chat, visible agent steps ("Searching knowledge base…"), source citations
- [ ] Booking confirmation card (Confirm / Change buttons → resume endpoint)
- [ ] Login page, "My appointments" page, medical disclaimer banner
- [ ] ESLint + Prettier + Playwright smoke test; frontend job in CI; npm entry in `dependabot.yml`
- **Done when:** a recruiter can open the site, chat, and book end-to-end.

## Phase 7 – Quality: observability & evaluation

- [ ] Langfuse tracing on every graph run (session = thread_id, user id hashed)
- [ ] `evals/`: golden datasets for RAG (reuse legacy `testset.csv`), routing, booking
- [ ] RAGAS: faithfulness, answer relevancy, context precision; DeepEval: task completion, tool correctness
- [ ] CI eval gate on PRs that touch `agents/`, `rag/`, prompts (thresholds in `evals/thresholds.yaml`)
- [ ] **RAG improvements, each measured before/after with RAGAS** (record a baseline on the Phase 2
  pipeline first, then change one thing at a time and keep a results table):
  - **Contextual chunk headers:** prepend the topic title and its "Also called" synonyms to every chunk
    before embedding (and before the `tsvector` is built), then re-ingest. Motivation: Phase 2 retrieval
    for "symptoms of diabetes" ranked a risk-factors chunk first because a mid-topic chunk carries no
    mention of its topic. Show the header in citations/prompt text only if it helps; the stored text
    can stay clean.
  - **Cross-encoder reranker:** a local cross-encoder behind the existing `Reranker` interface
    (compare against `ScoreReranker`: quality, latency, install size).
  - **Re-measure `RAG_MIN_SCORE`** on a larger labelled question set (in-scope, near-miss and off-topic;
    Phase 2 used only 18 questions with a narrow 0.65-0.74 gap). Re-do it after each change above,
    because the threshold is specific to the embedding model, chunk text and corpus.
- [ ] Results table + chart in README
- **Done when:** CI fails if faithfulness drops below threshold.

## Phase 8 – Deployment

- [ ] `infra/terraform/`: VPC, ECR, ECS Fargate (or App Runner), RDS Postgres (pgvector), Secrets Manager, CloudWatch logs
- [ ] GitHub Actions CD with **OIDC** to AWS (no long-lived keys): build → push ECR → deploy on tag
- [ ] Frontend on Vercel (or S3 + CloudFront)
- [ ] Custom domain + HTTPS, health checks, autoscaling min 1
- [ ] Cost guard: budgets alert; teardown instructions
- [ ] README: live link, architecture image, demo GIF, eval results, "what I'd do next"
- **Done when:** public URL is live and a tagged release deploys automatically.

---

## Stretch goals (good interview talking points)

- Semantic cache (Redis) for repeated questions
- Multilingual (English/German) answers
- Voice input (Whisper) in the chat UI
- Admin dashboard for doctors' schedules
- A/B test of prompts with Langfuse prompt management
