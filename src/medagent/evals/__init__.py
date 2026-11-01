"""Evaluation harness: frozen golden sets, pure scoring functions, suites and result files.

Scoring (`metrics.py`, `booking_judge.py`) is pure and unit-tested with no LLM. Suites in
`suites/` run the real system and feed the scorers; `scripts/run_evals.py` is the entry point.
"""

from medagent.evals import telemetry as _telemetry

_telemetry.disable()  # before ragas / deepeval can be imported by any entry point
