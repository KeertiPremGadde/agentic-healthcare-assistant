# 0028 – The eval gate in CI: a free job always, a paid job when it matters

Status: accepted (Phase 7)

## Context
`evals/thresholds.yaml` and `scripts/run_evals.py gate` (ADR 0013) define what a change must not break, but
they only run when someone remembers to. A prompt edit that costs 5 points of routing accuracy, or a refactor
that lets one booking write through before confirmation, would merge. The gate has to run on pull requests.

Two things make that hard: real model calls cost money and need an API key, and a pull request is code from
someone else (a fork, Dependabot) that must never get the key.

## Decision
One workflow, `.github/workflows/eval-gate.yml`, two jobs.

**`baselines` (free, no secret, every pull request).** The committed result files still satisfy the
thresholds (36 checks) and the datasets still match `datasets.lock.json`. It catches a threshold edited
without a baseline, a baseline replaced without its dataset version, and a dataset changed without a lock.

**`live` (paid, secret, only when it matters).** It runs the routing eval (100 messages x 3, about $0.06)
and the booking eval (27 scenarios, about $0.01) against the real model and gates them with the same
thresholds, so a result is judged by the rules that judged the baseline. It runs when:
- the pull request is from THIS repository, not a fork, and not from Dependabot (neither gets the secret);
- and the diff touches `src/medagent/agents|guardrails|rag|evals/`, `evals/`, `scripts/run_evals.py`, this
  workflow, `pyproject.toml` or `uv.lock`: the things the evals measure. A docs or frontend change spends nothing;
- and the free job passed (`needs`): no money is spent on an inconsistent repository.

Why routing and booking only: they need nothing but Postgres (the booking suite builds its own throwaway
database), so the job takes a few minutes. RAG, retrieval and the whole-bot red-team need the knowledge base
ingested and two models downloaded in CI (about 220 MB); that stays a manual run and a later workflow. The
red-team RULES are tested in the normal pytest job (they cost nothing).

**Safety of the key**, each point pinned by a test that reads the workflow YAML
(`tests/unit/test_eval_gate_workflow.py`, 12 unsafe edits each fail a test):
- `pull_request`, never `pull_request_target`: a fork's code does not run with the base repository's rights.
- The workflow can only read the repository (`permissions: contents: read`, no job overrides it).
- The key is passed as an environment variable to the three steps that need it and nowhere else, not at
  workflow or job level, and the free job has no secrets at all.
- Every paid command has `--max-usd` (0.15 and 0.10), and a new push cancels the run it replaces
  (`concurrency`), so spend is bounded per push and not multiplied by quick pushes.
- Dependencies are installed with `uv sync --frozen`; nothing from the pull request is interpolated into a
  shell script (the base branch goes through an environment variable).
- If the secret is missing on a same-repository pull request that needs the live gate, the job FAILS with a
  message pointing to the setup steps. It does not skip: a gate that silently does not run is worse than none.

## Consequences
- About $0.07 per push to a pull request that touches the agent, guardrails, RAG or evals; with 20 such
  pushes a month about $1.4. Use a separate API key with a spend limit (docs/SETUP.md).
- The result files and the gate output are kept as an artifact for 14 days and shown in the job summary.
- The routing and booking floors are wide on purpose (ADR 0025): model noise must not fail an unrelated
  push. A real regression of the size the baselines measure does.
- A change that only touches RAG or the red-team behaviour is covered by the free job and the unit tests,
  not by a live run, until the full workflow exists.
