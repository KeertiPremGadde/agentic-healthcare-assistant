# Contributing

1. Pick the next unchecked task in [docs/PLAN.md](docs/PLAN.md).
2. Branch from `main`: `git switch -c feat/phase1-data-layer`.
3. Commit with [Conventional Commits](https://www.conventionalcommits.org/): `feat(db): add appointment model`.
4. Before pushing: `uv run ruff check . ; uv run mypy src ; uv run pytest` (pre-commit runs ruff + gitleaks).
5. Open a PR using the template. CI must be green before merging (squash merge).
6. Record significant decisions as an ADR in `docs/adr/`.

## Code conventions

- Python 3.12, full type hints, `mypy --strict` clean.
- Domain logic in `services/` is pure and LLM-free; agents call it through `tools/`.
- Prompts live in `agents/prompts/`, never inline in node code.
- Settings only through `core/config.py`, never `os.getenv` scattered around.
- No PII in logs or traces; synthetic data only.
