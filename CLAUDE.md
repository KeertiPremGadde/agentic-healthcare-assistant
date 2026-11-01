# CLAUDE.md – guidance for Claude Code in this repo

## Project
MedAgent: agentic AI healthcare assistant (portfolio project for an AI Engineer role).
LangGraph multi-agent system + RAG + MCP tools + FastAPI + Next.js, deployed to AWS.

- Roadmap and current status: `docs/PLAN.md` (read it first, every session)
- Diagrams: `docs/ARCHITECTURE.md` · Decisions: `docs/adr/` · Setup: `docs/SETUP.md`

## How to work here
- Work **one phase at a time**, in order, on a branch `feat/phase<N>-<topic>`.
- Before coding a phase, show the user a short plan for it and wait for approval.
- After each task: run checks, tick the box in `docs/PLAN.md`, add to `CHANGELOG.md`.
- Commit in small Conventional Commits. Ask before pushing, creating PRs, or anything in AWS.
- No AI attribution anywhere: no `Co-Authored-By: Claude` trailer, no "Generated with Claude Code"
  line in commits, PR descriptions or docs.
- Explain new concepts briefly when introducing them: the user wants to learn and to talk
  about every part in interviews.

## Commands (Windows / PowerShell)
```
uv sync                                  # install deps (add deps with: uv add <pkg>)
uv run ruff check . ; uv run ruff format .
uv run mypy src
uv run pytest                            # -m "not llm" to skip real LLM calls
uv run python scripts/serve.py           # API; not plain uvicorn: on Windows psycopg async needs a SelectorEventLoop
docker compose up -d                     # Postgres + pgvector (Docker Desktop must be running)
```

## Conventions
- Python 3.12, src layout (`src/medagent`), full type hints, mypy strict.
- Add dependencies with `uv add` in the phase that needs them; never edit `uv.lock` by hand.
- Settings only via `medagent.core.config.get_settings()`.
- `services/` = pure domain logic (no LLM). `tools/` wrap services for agents. Prompts in `agents/prompts/`.
- LLM routing/extraction uses **structured output** (Pydantic), never string matching.
- Tests: unit tests use a fake LLM; mark real-LLM tests `@pytest.mark.llm`, DB tests `@pytest.mark.integration`.

## Hard rules
- Never commit secrets: `.env`, `credentials.json`, `token.pickle`, `secrets/` are git-ignored; keep it that way.
- Synthetic patient data only. No PII in logs or traces.
- Medical answers must cite sources and include the disclaimer; emergencies short-circuit to the emergency response.

## Legacy code (read-only references, do not modify)
- `D:\medical-chatbot-langgraph` – models, seed, availability/validation/doctor services
- `D:\Build-a-Complete-Medical-Chatbot-with-LLMs-LangChain-Pinecone-Flask-AWS` – RAG prompts,
  PDF data, Google Calendar helper, RAGAS evaluation. Its `credentials.json` / `token.pickle` must never be copied.
