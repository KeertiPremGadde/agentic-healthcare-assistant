"""The eval gate: compare result files with `evals/thresholds.yaml` (pure, no LLM).

`hard` rules must hold in EVERY run given; `gate` rules must hold for the MEAN over the runs.
A suite is checked only if at least one of its result files is given (so a CI job can run a
subset); a listed metric that is missing from a given suite is a failure, never a pass.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

THRESHOLDS_FILE = Path(__file__).resolve().parents[3] / "evals" / "thresholds.yaml"


@dataclass(frozen=True)
class Check:
    suite: str
    metric: str
    kind: str  # hard | gate
    rule: str  # e.g. "min 0.76"
    observed: float | None
    ok: bool


def load_thresholds(path: Path = THRESHOLDS_FILE) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _holds(rule: dict[str, float], value: float) -> bool:
    if "eq" in rule:
        return abs(value - rule["eq"]) < 1e-9
    if "min" in rule and value < rule["min"] - 1e-9:
        return False
    return not ("max" in rule and value > rule["max"] + 1e-9)


def _describe(rule: dict[str, float]) -> str:
    return ", ".join(f"{k} {v}" for k, v in rule.items())


def evaluate(thresholds: dict[str, Any], runs: list[dict[str, Any]]) -> list[Check]:
    by_suite: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_suite[run["suite"]].append(run)
    checks: list[Check] = []
    for suite, rules in thresholds["suites"].items():
        suite_runs = by_suite.get(suite)
        if not suite_runs:
            continue
        for kind in ("hard", "gate"):
            for metric, rule in (rules.get(kind) or {}).items():
                values = [r["metrics"].get(metric) for r in suite_runs]
                if any(v is None for v in values):
                    checks.append(Check(suite, metric, kind, _describe(rule), None, False))
                    continue
                if kind == "hard":  # every run
                    ok = all(_holds(rule, float(v)) for v in values)
                    observed = max(values, key=lambda v: abs(float(v) - rule.get("eq", 0.0)))
                else:  # the mean over runs
                    observed = sum(values) / len(values)
                    ok = _holds(rule, observed)
                checks.append(Check(suite, metric, kind, _describe(rule), round(observed, 4), ok))
    return checks


def load_runs(directory: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "suite" in data and "metrics" in data:
            runs.append(data)
    return runs
