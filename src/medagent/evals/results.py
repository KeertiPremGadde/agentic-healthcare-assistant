"""The result file every eval run writes, plus the spend budget that stops a run early."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from medagent.observability.cost import RunCost

RESULTS_DIR = Path(__file__).resolve().parents[3] / "evals" / "results"
SCHEMA_VERSION = 1


class Spend:
    """Running token/USD total for one run, with a hard cap."""

    def __init__(self, max_usd: float) -> None:
        self.max_usd = max_usd
        self.input_tokens = 0
        self.output_tokens = 0
        self.usd = 0.0
        self.calls = 0

    def add(self, cost: RunCost) -> None:
        self.input_tokens += cost.input_tokens
        self.output_tokens += cost.output_tokens
        self.usd += cost.usd
        self.calls += 1

    @property
    def exhausted(self) -> bool:
        """True once the cap is reached: jobs not yet started are skipped (running ones finish)."""
        return self.usd >= self.max_usd

    def abort_reason(self) -> str | None:
        return (
            f"budget cap ${self.max_usd:.2f} reached (spent ${self.usd:.4f})"
            if self.exhausted
            else None
        )

    def as_dict(self) -> dict[str, float | int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 5),
            "calls": self.calls,
        }


class EvalResult(BaseModel):
    schema_version: int = SCHEMA_VERSION
    suite: str
    run_id: str
    started_at: str
    git_sha: str | None
    model: str | None  # None for suites that call no LLM
    datasets: dict[str, dict[str, str]]  # name -> {version, sha256}
    params: dict[str, Any]
    metrics: dict[str, Any]
    hard_violations: list[str] = Field(default_factory=list)
    cost: dict[str, float | int] = Field(default_factory=dict)
    aborted: str | None = None  # reason, if the run stopped early (e.g. budget)
    items: list[dict[str, Any]] = Field(default_factory=list)  # per-question records


def git_sha() -> str | None:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def new_run_id(suite: str) -> str:
    return f"{suite}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"


def write_result(result: EvalResult, directory: Path | None = None) -> Path:
    target = (directory or RESULTS_DIR / "runs") / f"{result.run_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result.model_dump(), indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return target
