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

## Phase 1 – Data layer

- [x] Add deps: `sqlalchemy>=2`, `psycopg[binary]`, `alembic`, `pgvector`
- [x] `db/session.py` (engine + session dependency), port models with typed `Mapped[]` columns
- [x] Appointment: *partial* unique index on `(doctor_id, start_time) WHERE status='booked'` (cancelled slots can be rebooked), `status` enum + CHECK, timestamps
- [x] `DoctorSchedule` model (weekday, start, end in clinic timezone, `Europe/Berlin` via settings); all stored times UTC
- [x] Alembic init + first migration; `scripts/seed.py` (doctors, weekly schedules, synthetic patients)
- [x] Port `availability_service` + `validation_service` as pure functions (timezone-aware)
- [x] Unit tests for slot generation/validation; integration test against Docker Postgres
- **Done when:** `docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py` works and tests pass.

## Phase 2 – RAG knowledge base

- [ ] Add deps: `langchain-core`, `langchain-openai` (or `-anthropic`), `langchain-postgres`, `pypdf`, `langchain-text-splitters`
- [ ] `rag/ingest.py`: load PDFs → chunk → metadata (source, page) → embed → pgvector (idempotent)
- [ ] `rag/retriever.py`: hybrid search (vector + `tsvector`) with reciprocal-rank fusion, then reranker
- [ ] Answers include citations `[source p.N]`; "I don't know" when context is weak
- [ ] Tests with a tiny fixture corpus
- **Done when:** `uv run python -m medagent.rag.ingest` loads the PDFs and a CLI query returns cited answers.

## Phase 3 – Multi-agent graph (core of the project)

- [ ] Add deps: `langgraph`, `langgraph-checkpoint-postgres`
- [ ] `agents/state.py`: typed state with `messages` (add_messages reducer) + booking slots
- [ ] `guardrails/`: emergency detector (red-flag symptoms → stop + emergency number), scope check, PII masking for logs
- [ ] `agents/nodes/supervisor.py`: structured-output router → `medical_rag | doctor_finder | booking | smalltalk`
- [ ] `doctor_finder`: specialty as a Pydantic enum (no string matching), lists doctors via tool
- [ ] `booking`: extracts doctor/date/time/patient from natural language, checks availability, **`interrupt()` for confirmation**, books in a transaction
- [ ] Output guard: disclaimer + groundedness check for RAG answers
- [ ] `agents/graph.py`: compile with Postgres checkpointer; export graph PNG to `docs/diagrams/`
- [ ] Tests: router decisions with a fake LLM, booking happy path + conflict + past date
- **Done when:** a CLI chat can answer a question, recommend a cardiologist and book a slot with confirmation, and memory survives restart.

## Phase 4 – Tools & integrations (MCP)

- [ ] `mcp_server/`: expose `search_doctors`, `check_availability`, `book_appointment`, `cancel_appointment` via the official MCP Python SDK
- [ ] Agents load tools through the MCP client adapter (`langchain-mcp-adapters`)
- [ ] Google Calendar event on booking (port `calendar_helper.py`, service-account or OAuth, secrets outside repo)
- [ ] Confirmation email (e.g. Resend/SES), optional
- **Done when:** the MCP server works in MCP Inspector and the graph books through it.

## Phase 5 – API

- [ ] `POST /v1/chat` streaming via SSE (tokens + tool-step events), `thread_id` per conversation
- [ ] `POST /v1/chat/{thread_id}/resume` for HITL confirmation
- [ ] `GET /v1/appointments` (own appointments), `DELETE` to cancel
- [ ] JWT auth (register/login, hashed passwords), rate limiting, request IDs, error handlers
- [ ] OpenAPI docs clean; API tests with httpx
- **Done when:** the full flow works from `/docs` (Swagger) and with `curl`.

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
