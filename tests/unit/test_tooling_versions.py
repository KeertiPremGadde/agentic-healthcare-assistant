"""The pre-commit hooks and `uv run` must use the same ruff, or a commit can fail on a rule the
project's own `ruff check` does not report (and the reverse). Happened once: v0.8.4 vs 0.17.3."""

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _locked_ruff() -> str:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    return next(p["version"] for p in lock["package"] if p["name"] == "ruff")


def _hook_ruff() -> str:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    repo = next(r for r in config["repos"] if r["repo"].endswith("ruff-pre-commit"))
    return str(repo["rev"]).removeprefix("v")


def test_pre_commit_ruff_matches_the_locked_ruff() -> None:
    assert _hook_ruff() == _locked_ruff(), (
        "bump rev in .pre-commit-config.yaml to the version in uv.lock (or the reverse)"
    )
