"""Switch off the analytics of the eval libraries, before they are imported.

ragas and DeepEval both report anonymous usage events by default (DeepEval to PostHog). Nothing
about patients or questions is in them, but "no third party gets anything we did not decide" is
the rule of this project, so it is switched off here and checked after the libraries are imported
(`assert_off`). Imported by `medagent.evals`, so every entry point is covered.
"""

import os
import sys

_ENV = {
    "RAGAS_DO_NOT_TRACK": "true",
    "DEEPEVAL_TELEMETRY_OPT_OUT": "YES",
    "DEEPEVAL_DISABLE_DOTENV": "1",  # deepeval would otherwise load .env into the environment
}


def disable() -> None:
    """Force the opt-out variables (a value set in the shell does not win)."""
    os.environ.update(_ENV)


def assert_off() -> None:
    """Raise if an imported library would still report. Call after importing ragas/deepeval."""
    if "ragas" in sys.modules:
        from ragas._analytics import do_not_track

        if not do_not_track():
            raise RuntimeError("ragas telemetry is on")
    if "deepeval" in sys.modules:
        from deepeval.telemetry.client import telemetry_opt_out

        if not telemetry_opt_out():
            raise RuntimeError("deepeval telemetry is on")
