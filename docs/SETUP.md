# Setup – Windows

## Status of this machine (checked 2026-10-31)

| Tool | Status | Needed for |
|---|---|---|
| Python 3.14 + **uv 0.9** | ✅ installed | uv installs Python 3.12 for the project automatically |
| Git 2.45 | ✅ (user configured) | everything |
| VS Code | ✅ | development |
| Docker 29 | ✅ installed, **Docker Desktop not running** | Postgres (Phase 1+) |
| Node 22 LTS / npm 11 | ✅ (Node 22 pinned in `frontend/.nvmrc`; newer also works locally) | frontend |
| AWS CLI 2 | ✅ | deploy (Phase 8) |
| GitHub CLI `gh` | ❌ missing | create repo + PRs from terminal |
| Terraform | ❌ missing | infrastructure (Phase 8) |

## Install the missing pieces

```powershell
winget install --id GitHub.cli
winget install --id Hashicorp.Terraform
winget install --id OpenJS.NodeJS.LTS      # Node 22 LTS (the frontend and CI use 22)
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
uv run python scripts/serve.py                # API: http://localhost:8000/docs and /demo
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

## The API (Phase 5)

```powershell
uv run python scripts/serve.py        # http://localhost:8000/docs   (and /demo in local mode)
```

On Windows use `scripts/serve.py`, not plain `uvicorn`: it starts the event loop the Postgres
checkpointer needs. The server needs Docker Postgres running and `ANTHROPIC_API_KEY` in `.env`.

### JWT_SECRET (required outside local mode)

`JWT_SECRET` signs login tokens: anyone who knows it can forge a login for any user. Generate a
strong one and put the output in `.env` (never commit it, never paste it into chat):

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```
JWT_SECRET=<the 64-character output>
```

With `APP_ENV=local` the placeholder `change-me` is accepted so development works out of the box;
any other `APP_ENV` refuses to start unless the secret is 32+ random characters. Changing the
secret logs everyone out (existing tokens stop verifying).

### Try it in the browser (/docs)

1. Open http://localhost:8000/docs.
2. `POST /v1/auth/register` -> *Try it out*: username e.g. `demo1`, password of 10+ characters.
   Use fake data only.
3. Click **Authorize** (top right), enter the same username and password, **Authorize**.
4. `POST /v1/chat`: set `stream` to `false`, body `{"message": "I have an itchy rash, who should I
   see?"}`. Copy `conversation_id` from the reply.
5. `POST /v1/chat` again with `{"message": "Book number 1 tomorrow morning", "conversation_id":
   "<id>"}`. The reply has `pending`: the assistant is waiting for your yes/no.
6. `POST /v1/chat/{conversation_id}/resume` with `{"confirmed": true}`.
7. `GET /v1/appointments` lists it; `DELETE /v1/appointments/{id}` cancels it.

To watch the live stream, open http://localhost:8000/demo (local mode only), or:

```powershell
curl.exe -N -X POST http://localhost:8000/v1/chat -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d "{\"message\": \"Hi, what can you do?\"}"
```

Limits (all configurable in `.env`): 1,000 characters per message, 50 messages per user per day,
and a global daily budget of `DAILY_BUDGET_USD` (default 1.00); past it, chat answers "demo limit
reached" and makes no LLM calls (emergency messages still get the emergency answer).

## Run the frontend

```powershell
docker compose up -d
uv run python scripts/serve.py          # API on http://localhost:8000
cd frontend
npm ci
npx playwright install chromium         # once, for the browser tests
npm run dev                             # http://localhost:3000
```

The API must allow the frontend's origin: `API_CORS_ORIGINS=http://localhost:3000` (the default in
`.env.example`). Register any username on the login page (no email needed), then try the example
prompts. See `frontend/README.md` for the scripts.

## Tracing with Langfuse (optional)

Every graph run can be inspected as a trace: which nodes ran, how long each took, tokens and cost.
By default **no message text, passages or ids are sent** (see ADR 0012).

1. Sign up at [cloud.langfuse.com](https://cloud.langfuse.com) (free Hobby plan, no card). Choose the
   **EU** region unless you prefer US.
2. Create an organisation and a project (for example `medagent`).
3. Project settings, API Keys, "Create new API key". Copy the public key (`pk-lf-...`) and the secret
   key (`sk-lf-...`, shown once).
4. Put them in `.env` yourself (it is git-ignored; never paste keys in chat or commit them):
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   ```
   `LANGFUSE_ENABLED`, `LANGFUSE_CAPTURE_CONTENT` (keep `false`) and `LANGFUSE_SAMPLE_RATE` are
   optional; see `.env.example`.
5. Check the setup (sends no conversation data): `uv run python scripts/check_langfuse.py`.
6. Start the API (`uv run python scripts/serve.py`), chat, and open the project's Tracing page: one
   trace per turn named `medagent.turn`, grouped into a session per conversation. Message text shows
   as `[redacted: N chars]`; that is intended.

The free tier allows 50k units a month (traces, observations and scores). A turn costs about 17 to
19 units. Lower `LANGFUSE_SAMPLE_RATE` if you expect more.

## Running the evaluations (Phase 7)

```powershell
uv run python scripts/run_evals.py retrieval        # free, no LLM (also prints the RAG_MIN_SCORE margins)
uv run python scripts/run_evals.py retrieval --dataset threshold_dev   # free: the threshold tuning set
uv run python scripts/run_evals.py retrieval-de --repeats 3            # German via the router (a few cents)
uv run python scripts/run_evals.py routing --repeats 3 --max-usd 0.5
uv run python scripts/run_evals.py gate --results evals/results/baseline-deterministic evals/results/baseline-judged
```

The LLM-judged metrics (ragas, DeepEval) live in their own environment with its own lock file
(`evals/pyproject.toml`), because those libraries pin older `click`, `rich`, `jiter` and `fsspec`
than the app uses:

```powershell
uv sync --project evals                                # once; large (about 1 GB)
uv run --project evals python scripts/run_evals.py judge-rag --source evals/results/runs/rag-<id>.json
uv run --project evals python scripts/run_evals.py judge-booking --source evals/results/runs/booking-<id>.json
```

Every LLM suite takes `--max-usd` and stops starting calls at the cap. The telemetry of both
libraries is switched off in code (`src/medagent/evals/telemetry.py`) and a test pins it.
Windows note: close the VS Code mypy/Python language server before `uv sync` in the main
environment, or it holds `.pyd` files open ("Access is denied").
