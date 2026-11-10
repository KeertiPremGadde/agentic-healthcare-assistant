# Setup

The commands below are for Windows PowerShell; on macOS or Linux they are the same apart from
`copy` (use `cp`).

## Requirements

| Tool | Version | Needed for |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.9+ | Python environment (installs Python 3.12 itself) |
| Docker Desktop | any recent | Postgres + pgvector |
| Node.js | 22 LTS (pinned in `frontend/.nvmrc`) | frontend |
| GitHub CLI `gh` | optional | setting the CI secret |
| AWS CLI 2, Terraform | optional | deployment |

## API keys

| Key | Needed for | Where it goes |
|---|---|---|
| `ANTHROPIC_API_KEY` (or an OpenAI key) | chat, routing, answers | `.env` |
| Google service account (optional) | Google Calendar sync | `secrets/` (git-ignored) |
| Langfuse keys (optional) | tracing | `.env` |

## First run

Start Docker Desktop first, then:

```powershell
git clone https://github.com/KeertiPremGadde/agentic-healthcare-assistant.git
cd agentic-healthcare-assistant
copy .env.example .env                        # then add ANTHROPIC_API_KEY
uv sync
uv run pre-commit install
docker compose up -d                          # Postgres + pgvector on :5432
uv run alembic upgrade head                   # create the schema
uv run python scripts/seed.py                 # synthetic doctors, schedules, patients (idempotent)
uv run python scripts/fetch_medlineplus.py    # download MedlinePlus topics into data/raw/ (git-ignored)
uv run python -m medagent.rag.ingest medlineplus   # embed locally (FastEmbed, no API key) into pgvector
uv run pytest -m "not llm"                    # tests without real LLM calls
uv run python scripts/serve.py                # API: http://localhost:8000/docs
```

Quick checks without the web app:

```powershell
uv run python -m medagent.rag.ask "What are the symptoms of diabetes?"
uv run python -m medagent.agents.chat --patient alex.example@example.com   # add --verbose for cost logs
```

## Recommended VS Code extensions

See `.vscode/extensions.json` (VS Code suggests them when you open the folder): Python, Ruff,
Mypy, Docker, Mermaid preview, Even Better TOML, GitHub Actions, Terraform.

## MCP server

```powershell
uv run python -m medagent.mcp_server                    # stdio server (the chat starts it itself)
uv run mcp dev src/medagent/mcp_server/server.py        # open it in MCP Inspector (needs Node/npx)
```

Any MCP client can launch the stdio server with the command above (use absolute paths in its configuration).

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

## The API

```powershell
uv run python scripts/serve.py        # http://localhost:8000/docs   (and /demo in local mode)
```

On Windows use `scripts/serve.py`, not plain `uvicorn`: it starts the event loop the Postgres
checkpointer needs. The server needs Docker Postgres running and `ANTHROPIC_API_KEY` in `.env`.

### JWT_SECRET (required outside local mode)

`JWT_SECRET` signs login tokens: anyone who knows it can forge a login for any user. Generate a
strong one and put the output in `.env` (never commit it):

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
   Use made-up data only.
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
4. Put them in `.env` yourself (it is git-ignored; never commit keys):
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

## Running the evaluations

```powershell
uv run python scripts/run_evals.py retrieval        # free, no LLM (also prints the RAG_MIN_SCORE margins)
uv run python scripts/run_evals.py retrieval --dataset threshold_dev   # free: the threshold tuning set
uv run python scripts/run_evals.py retrieval-de --repeats 3            # German via the router (a few cents)
uv run python scripts/run_evals.py routing --repeats 3 --max-usd 0.5
uv run python scripts/run_evals.py redteam --pilot --repeats 1     # about $0.02: 2 cases per group
uv run python scripts/run_evals.py redteam --max-usd 0.60          # full red-team run, about $0.23
uv run python scripts/run_evals.py redteam-rescore --source <file> # free: re-score a saved run
uv run python scripts/run_evals.py gate --results evals/results/baseline-deterministic evals/results/baseline-judged evals/results/redteam-baseline
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

## Eval gate in CI

`.github/workflows/eval-gate.yml` has two jobs (ADR 0028). The free one needs nothing. The paid one runs the
routing and booking evals against the real model on pull requests from this repository that touch the agent,
guardrails, RAG, evals or dependencies, and needs one repository secret. It costs about $0.07 a run.

Set it up once:

1. **Create a separate key with a spend limit.** In the Anthropic Console, make a workspace for CI (for
   example `medagent-ci`), set its monthly spend limit to a few dollars, and create an API key inside it
   named `medagent-ci-eval`. Do not reuse the key in your `.env`.
2. **Store it as a repository secret** (the command asks for the value and does not echo it):
   ```powershell
   gh secret set ANTHROPIC_API_KEY --repo KeertiPremGadde/agentic-healthcare-assistant
   ```
3. **Check it exists** (shows the name and date, never the value):
   ```powershell
   gh secret list --repo KeertiPremGadde/agentic-healthcare-assistant
   ```
4. **See it work.** The pull request that adds the workflow runs it (the live job is triggered because the
   workflow file itself is on the list of paths it watches). After it has merged you can also start it by hand:
   Actions, "Eval gate", "Run workflow", or `gh workflow run eval-gate.yml`. The job summary shows the gate
   output and the result files are attached to the run for 14 days.

Until the secret exists, a pull request that needs the live gate fails with a message that points here.
Pull requests from forks and Dependabot skip the paid job (they get no secret). To rotate the key, create a new
one, run step 2 again and delete the old key in the Console.
