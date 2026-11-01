"""Run an evaluation suite and write a result file to evals/results/runs/.

    uv run python scripts/run_evals.py retrieval                      # free (no LLM)
    uv run python scripts/run_evals.py routing --repeats 3 --max-usd 0.5
    uv run python scripts/run_evals.py rag --per-kind 2 --max-usd 0.2   # a small pilot sample
    uv run python scripts/run_evals.py booking --only b01,b11,b23 --max-usd 0.3

Every LLM suite stops starting new calls once --max-usd is reached and still writes its file.
Content is never sent to Langfuse (these runs are untraced).
"""

import argparse
import json

from medagent.core import aio
from medagent.core.logging import configure_logging
from medagent.evals import datasets, suites
from medagent.evals.booking_suite import run_booking
from medagent.evals.results import EvalResult, Spend, write_result


def _print(result: EvalResult, path: object) -> None:
    print(f"\n{result.suite} · model={result.model} · git={result.git_sha}")
    for name, value in result.metrics.items():
        if isinstance(value, dict | list):
            continue
        print(f"  {name:38} {value}")
    if result.hard_violations:
        print("  HARD VIOLATIONS:", result.hard_violations)
    if result.cost:
        c = result.cost
        print(
            f"  cost: {c['input_tokens']} in / {c['output_tokens']} out tokens, "
            f"${c['usd']}, {c['calls']} calls"
        )
    if result.aborted:
        print("  ABORTED:", result.aborted)
    print(f"  written: {path}")


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("suite", choices=["retrieval", "routing", "rag", "booking"])
    p.add_argument("--repeats", type=int, default=3, help="routing: runs per message")
    p.add_argument("--limit", type=int, default=None, help="routing/rag: first N items")
    p.add_argument("--per-kind", type=int, default=None, help="rag: N questions of each kind")
    p.add_argument("--only", default=None, help="booking: comma-separated scenario ids")
    p.add_argument("--max-usd", type=float, default=1.0, help="stop starting calls above this")
    p.add_argument("--check-lock", action="store_true", help="fail if a dataset changed")
    args = p.parse_args()
    configure_logging()

    if args.check_lock:
        lock = json.loads(datasets.LOCK_FILE.read_text(encoding="utf-8"))
        if lock != datasets.current_hashes():
            raise SystemExit("dataset changed without a new version/lock (datasets.lock.json)")

    spend = Spend(args.max_usd)
    if args.suite == "retrieval":
        result = suites.run_retrieval()
    elif args.suite == "routing":
        result = await suites.run_routing(spend, args.repeats, args.limit)
    elif args.suite == "rag":
        result = await suites.run_rag(spend, args.limit, args.per_kind)
    else:
        only = args.only.split(",") if args.only else None
        result = await run_booking(spend, only)
    _print(result, write_result(result))


if __name__ == "__main__":
    aio.run(main())
