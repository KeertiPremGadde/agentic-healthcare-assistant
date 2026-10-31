# Handoff prompt for Claude Code in VS Code

Open `D:\agentic-healthcare-assistant` in VS Code, open the Claude Code panel, and paste:

---

You are continuing the MedAgent project (agentic AI healthcare assistant) in this repo.
Phase 0 (foundation) is scaffolded but not yet installed or committed.

1. Read `CLAUDE.md`, `docs/PLAN.md`, `docs/ARCHITECTURE.md` and `docs/SETUP.md` fully before doing anything.
2. Finish Phase 0:
   - Check Docker Desktop is running, then run `uv sync`, `uv run pre-commit install`,
     `uv run ruff check .`, `uv run mypy src`, `uv run pytest` and fix anything that fails.
   - Make the first commit on `main` (Conventional Commit, e.g. `chore: project foundation`).
   - Help me create the GitHub repo `agentic-healthcare-assistant` (public) with `gh repo create`
     and push, after I confirm. Then replace `YOUR_GITHUB_USERNAME` in `README.md` and
     `.github/CODEOWNERS`.
3. Then start **Phase 1 – Data layer**: show me your plan for it first, wait for my OK, work on
   branch `feat/phase1-data-layer`, port the legacy models/services listed in `docs/PLAN.md`
   (read-only from `D:\medical-chatbot-langgraph`), write tests, tick the PLAN boxes, update
   CHANGELOG, and open a PR when the phase is done.

Rules: one phase at a time; explain new concepts briefly as you go (I want to explain every part
in interviews); ask before pushing, creating PRs, or touching AWS; never copy `credentials.json`
or `token.pickle` from the legacy folders.

---

## Prompt for each later phase

> Read `CLAUDE.md` and `docs/PLAN.md`. Start the next unchecked phase. Show me the plan first,
> then build it on a `feat/phase<N>-...` branch with tests, update the docs, and open a PR.
