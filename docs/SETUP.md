# Setup – Windows

## Status of this machine (checked 2026-10-31)

| Tool | Status | Needed for |
|---|---|---|
| Python 3.14 + **uv 0.9** | ✅ installed | uv installs Python 3.12 for the project automatically |
| Git 2.45 | ✅ (user configured) | everything |
| VS Code | ✅ | development |
| Docker 29 | ✅ installed, **Docker Desktop not running** | Postgres (Phase 1+) |
| Node 20 / npm 11 | ✅ (Node 22 LTS recommended) | frontend (Phase 6) |
| AWS CLI 2 | ✅ | deploy (Phase 8) |
| GitHub CLI `gh` | ❌ missing | create repo + PRs from terminal |
| Terraform | ❌ missing | infrastructure (Phase 8) |

## Install the missing pieces

```powershell
winget install --id GitHub.cli
winget install --id Hashicorp.Terraform
winget install --id OpenJS.NodeJS.LTS      # upgrades Node 20 -> 22 LTS (optional now, needed by Phase 6)
```

Then open a new terminal and log in:

```powershell
gh auth login
```

Start **Docker Desktop** from the Start menu (it must be running for `docker compose`).

## Accounts / keys you will need

| When | What | Where it goes |
|---|---|---|
| Phase 2 | OpenAI (or Anthropic) API key | `.env` |
| Phase 4 | Google Cloud project + Calendar API credentials | `secrets/` (git-ignored) |
| Phase 7 | Langfuse Cloud project (free tier) | `.env` |
| Phase 8 | AWS account with billing alerts, Vercel account | GitHub Actions secrets / OIDC role |

## First run

```powershell
cd D:\agentic-healthcare-assistant
copy .env.example .env
uv sync
uv run pre-commit install
uv run pytest
uv run uvicorn medagent.main:app --reload     # http://localhost:8000/health and /docs
docker compose up -d                          # Postgres + pgvector on :5432
uv run alembic upgrade head                   # create/upgrade the schema
uv run python scripts/seed.py                 # synthetic doctors, schedules, patients (idempotent)
uv run python scripts/fetch_medlineplus.py     # download MedlinePlus topics into data/raw/ (git-ignored)
uv run python -m medagent.rag.ingest medlineplus   # embed locally (FastEmbed, no API key) into pgvector
uv run python -m medagent.rag.ask "What are the symptoms of diabetes?"   # needs ANTHROPIC_API_KEY
uv run python -m medagent.agents.chat --patient alex.example@example.com   # full agent (add --verbose for cost logs)
```

## Recommended VS Code extensions

See `.vscode/extensions.json` (VS Code suggests them when you open the folder): Python, Ruff,
Mypy, Docker, Mermaid preview, Even Better TOML, GitHub Actions, Terraform.

## MCP server (Phase 4)

```powershell
uv run python -m medagent.mcp_server                    # stdio server (the chat starts it itself)
uv run mcp dev src/medagent/mcp_server/server.py        # open it in MCP Inspector (needs Node/npx)
```

Claude Desktop (optional): add to `claude_desktop_config.json`, with absolute paths:

```json
{"mcpServers": {"medagent-clinic": {"command": "D:/agentic-healthcare-assistant/.venv/Scripts/python.exe",
  "args": ["-m", "medagent.mcp_server"], "cwd": "D:/agentic-healthcare-assistant"}}}
```

The server is meant for trusted local clients only (stdio); `book_appointment` takes a `patient_id`.

## Google Calendar (optional)

Booking works without it. To add appointments to one shared demo calendar via a service account:

1. Google Cloud Console (an existing project is fine): **APIs & Services → Library** → enable
   *Google Calendar API*.
2. **IAM & Admin → Service accounts → Create service account** (no roles needed).
3. Service account → **Keys → Add key → Create new key → JSON**; move the file to
   `secrets/google-calendar-sa.json` (git-ignored). Never commit or share it.
4. calendar.google.com → **Other calendars → + → Create new calendar** "MedAgent Demo Clinic"
   (time zone Berlin).
5. That calendar's **Settings and sharing → Share with specific people** → add the service
   account email → *Make changes to events*. Don't make the calendar public.
6. **Integrate calendar → Calendar ID** (`...@group.calendar.google.com`).
7. `.env`: `GOOGLE_SERVICE_ACCOUNT_FILE=secrets/google-calendar-sa.json` and
   `GOOGLE_CALENDAR_ID=<calendar id>` (not `primary`).
8. Check: `uv run python scripts/check_calendar.py` (creates and deletes one test event).
