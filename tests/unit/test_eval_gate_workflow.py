"""The eval-gate workflow (ADR 0028): what it may and may not do, checked from the YAML itself.

The paid job spends money and holds an API key. These tests pin the properties that keep that safe,
so an edit that opens a hole fails here before it reaches a pull request."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "eval-gate.yml"


def _load() -> dict[str, Any]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML reads a bare `on` as the boolean True
    return data  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def wf() -> dict[str, Any]:
    return _load()


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job["steps"]  # type: ignore[no-any-return]


def test_it_never_runs_with_the_privileges_of_the_base_repository(wf: dict[str, Any]) -> None:
    assert set(wf["on"]) == {"pull_request", "workflow_dispatch"}  # no pull_request_target


def test_the_workflow_can_only_read_the_repository(wf: dict[str, Any]) -> None:
    assert wf["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in wf["jobs"].values())


def test_a_new_push_cancels_the_run_it_replaces(wf: dict[str, Any]) -> None:
    assert wf["concurrency"]["cancel-in-progress"] is True


def test_the_secret_is_only_in_the_steps_that_call_the_api(wf: dict[str, Any]) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("secrets.ANTHROPIC_API_KEY") == 3  # the key check, routing, booking
    assert "secrets." not in str(wf["jobs"]["baselines"])
    assert "secrets." not in str(wf.get("env", {}))
    assert "secrets." not in str(wf["jobs"]["live"].get("env", {}))
    for step in _steps(wf["jobs"]["live"]):
        uses_key = "secrets.ANTHROPIC_API_KEY" in str(step.get("env", {}))
        assert uses_key == (
            step.get("name", "").startswith(("Routing eval", "Booking eval", "Require the API key"))
        )


def test_the_paid_job_is_closed_to_forks_and_dependabot(wf: dict[str, Any]) -> None:
    condition = wf["jobs"]["live"]["if"]
    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition
    assert "github.actor != 'dependabot[bot]'" in condition


def test_no_money_is_spent_while_the_free_job_fails(wf: dict[str, Any]) -> None:
    assert wf["jobs"]["live"]["needs"] == "baselines"


def test_every_paid_command_has_a_spending_cap(wf: dict[str, Any]) -> None:
    paid = [
        s["run"]
        for s in _steps(wf["jobs"]["live"])
        if re.search(r"run_evals\.py (routing|booking)", s.get("run", ""))
    ]
    assert len(paid) == 2
    for command in paid:
        match = re.search(r"--max-usd (\d+\.\d+)", command)
        assert match and float(match.group(1)) <= 0.20, command


def test_the_dependencies_come_from_the_lock_file(wf: dict[str, Any]) -> None:
    for name, job in wf["jobs"].items():
        runs = [s["run"] for s in _steps(job) if "uv sync" in s.get("run", "")]
        assert runs and all("--frozen" in r for r in runs), name


def test_the_free_job_gates_the_same_baselines_the_unit_test_checks(wf: dict[str, Any]) -> None:
    command = " ".join(
        s["run"] for s in _steps(wf["jobs"]["baselines"]) if "run_evals.py gate" in s.get("run", "")
    )
    assert "--check-lock" in command
    committed = {p.name for p in (ROOT / "evals" / "results").iterdir() if p.is_dir()}
    for directory in re.findall(r"evals/results/([\w-]+)", command):
        assert directory in committed
    assert {"baseline-deterministic", "baseline-judged", "redteam-baseline"} <= set(
        re.findall(r"evals/results/([\w-]+)", command)
    )


def _relevant_pattern(wf: dict[str, Any]) -> re.Pattern[str]:
    script = next(s["run"] for s in _steps(wf["jobs"]["live"]) if s.get("id") == "changes")
    return re.compile(re.search(r"grep -Eq '([^']+)'", script).group(1))  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "path",
    [
        "src/medagent/agents/prompts/router.py",
        "src/medagent/agents/nodes/supervisor.py",
        "src/medagent/guardrails/emergency.py",
        "src/medagent/rag/answer.py",
        "src/medagent/evals/metrics.py",
        "evals/thresholds.yaml",
        "evals/datasets/routing_golden.json",
        "scripts/run_evals.py",
        ".github/workflows/eval-gate.yml",
        "uv.lock",
        "pyproject.toml",
    ],
)
def test_a_change_to_what_the_evals_measure_runs_the_live_gate(
    wf: dict[str, Any], path: str
) -> None:
    assert _relevant_pattern(wf).search(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/PLAN.md",
        "README.md",
        "frontend/src/lib/types.ts",
        "CHANGELOG.md",
        "src/medagent/api/routes/chat.py",
        "tests/unit/test_evals.py",
    ],
)
def test_an_unrelated_change_does_not_spend_money(wf: dict[str, Any], path: str) -> None:
    assert not _relevant_pattern(wf).search(path)


def test_the_branch_name_never_reaches_the_shell_as_code(wf: dict[str, Any]) -> None:
    """`${{ ... }}` inside a `run:` script is text substitution: pass it through env instead."""
    for job in wf["jobs"].values():
        for step in _steps(job):
            assert "${{" not in step.get("run", ""), step.get("name")
