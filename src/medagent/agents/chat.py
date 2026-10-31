"""Terminal chat with the agent graph (real LLM, real database, Postgres memory).

    uv run python -m medagent.agents.chat --patient alex.example@example.com
    uv run python -m medagent.agents.chat --patient alex.example@example.com --thread demo-1
    uv run python -m medagent.agents.chat --patient alex.example@example.com --verbose

Re-use the same --thread to continue a conversation after a restart, including a booking
that is still waiting for your confirmation.
"""

import argparse
import uuid

from medagent.agents.checkpointer import postgres_checkpointer
from medagent.agents.deps import default_deps
from medagent.agents.graph import build_graph
from medagent.agents.runner import TurnResult, run_turn, turn_config
from medagent.core.config import get_settings
from medagent.core.logging import configure_logging
from medagent.db import repository
from medagent.db.session import get_sessionmaker


def _print_turn(result: TurnResult) -> None:
    if result.reply:
        print(f"\nMedAgent: {result.reply}")
    cost = result.cost
    print(f"  [{cost.input_tokens} in / {cost.output_tokens} out tokens, ~${cost.usd:.4f}]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--patient", required=True, help="email of a seeded synthetic patient")
    parser.add_argument("--thread", default=None, help="conversation id (default: new)")
    parser.add_argument(
        "--verbose", action="store_true", help="show the JSON run logs (tokens, cost, latency)"
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging("INFO" if args.verbose else "WARNING")  # graph_run logs at INFO
    with get_sessionmaker()() as session:
        patient = repository.get_patient_by_email(session, args.patient)
    if patient is None:
        raise SystemExit(f"No patient with email {args.patient}. Run scripts/seed.py first.")
    thread_id = args.thread or f"cli-{uuid.uuid4().hex[:8]}"
    print(f"Thread: {thread_id}  (model: {settings.llm_model}; Ctrl+C or 'quit' to exit)")

    with postgres_checkpointer() as saver:
        graph = build_graph(default_deps(settings), saver)
        # A booking may still be waiting from a previous run of this thread.
        pending = graph.get_state(turn_config(thread_id, patient.id)).interrupts
        result: TurnResult | None = None
        if pending:
            print("\n(Resuming a booking that is waiting for your confirmation.)")
        while True:
            question = None
            if pending:
                question = pending[0].value.get("question", "Confirm?")
            elif result is not None and result.pending:
                question = result.pending.get("question", "Confirm?")
            try:
                prompt = f"\nMedAgent: {question} [y/n] " if question else "\nYou: "
                text = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                text = "quit"  # the conversation (and any pending booking) is already saved
            if text.lower() in {"quit", "exit"}:
                print(f"\nBye. Continue later with --thread {thread_id}")
                break
            if question:
                confirmed = text.lower() in {"y", "yes", "ja", "j"}
                result = run_turn(graph, thread_id, patient.id, resume=confirmed)
                pending = ()
            else:
                if not text:
                    continue
                result = run_turn(graph, thread_id, patient.id, message=text)
            _print_turn(result)


if __name__ == "__main__":
    main()
