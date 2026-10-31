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
```

## Recommended VS Code extensions

See `.vscode/extensions.json` (VS Code suggests them when you open the folder): Python, Ruff,
Mypy, Docker, Mermaid preview, Even Better TOML, GitHub Actions, Terraform.
