"""Terminal chat with the agent graph (real LLM, real database, Postgres memory, MCP tools).

    uv run python -m medagent.agents.chat --patient alex.example@example.com
    uv run python -m medagent.agents.chat --patient alex.example@example.com --thread demo-1
    uv run python -m medagent.agents.chat --patient alex.example@example.com --verbose

Re-use the same --thread to continue a conversation after a restart, including a booking or
cancellation that is still waiting for your confirmation.
"""

import argparse
import asyncio
import uuid

from medagent.agents.checkpointer import postgres_checkpointer
from medagent.agents.deps import default_deps, open_tools
from medagent.agents.graph import build_graph
from medagent.agents.runner import TurnResult, run_turn, turn_config
from medagent.core import aio
from medagent.core.config import get_settings
from medagent.core.logging import configure_logging
from medagent.db import repository
from medagent.db.session import get_sessionmaker


def _print_turn(result: TurnResult) -> None:
    if result.reply:
        print(f"\nMedAgent: {result.reply}")
    cost = result.cost
    print(f"  [{cost.input_tokens} in / {cost.output_tokens} out tokens, ~${cost.usd:.4f}]")


async def chat(patient_email: str, thread: str | None) -> None:
    settings = get_settings()
    with get_sessionmaker()() as session:
        patient = repository.get_patient_by_email(session, patient_email)
    if patient is None:
        raise SystemExit(f"No patient with email {patient_email}. Run scripts/seed.py first.")
    thread_id = thread or f"cli-{uuid.uuid4().hex[:8]}"
    print(
        f"Thread: {thread_id}  (model: {settings.llm_model}, tools: {settings.tools_transport}; "
        "Ctrl+C or 'quit' to exit)"
    )

    async with open_tools(settings) as tools, postgres_checkpointer() as saver:
        graph = build_graph(default_deps(tools, settings), saver)
        # A confirmation may still be waiting from a previous run of this thread.
        snapshot = await graph.aget_state(turn_config(thread_id, patient.id))
        pending = snapshot.interrupts
        result: TurnResult | None = None
        if pending:
            print("\n(Resuming: something is waiting for your confirmation.)")
        while True:
            question = None
            if pending:
                question = pending[0].value.get("question", "Confirm?")
            elif result is not None and result.pending:
                question = result.pending.get("question", "Confirm?")
            try:
                prompt = f"\nMedAgent: {question} [y/n] " if question else "\nYou: "
                text = (await asyncio.to_thread(input, prompt)).strip()
            except (EOFError, KeyboardInterrupt):
                text = "quit"  # the conversation (and any pending confirmation) is already saved
            if text.lower() in {"quit", "exit"}:
                print(f"\nBye. Continue later with --thread {thread_id}")
                break
            if question:
                confirmed = text.lower() in {"y", "yes", "ja", "j"}
                result = await run_turn(graph, thread_id, patient.id, resume=confirmed)
                pending = ()
            else:
                if not text:
                    continue
                result = await run_turn(graph, thread_id, patient.id, message=text)
            _print_turn(result)


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
    configure_logging("INFO" if args.verbose else "WARNING")  # graph_run logs at INFO
    aio.run(chat(args.patient, args.thread))


if __name__ == "__main__":
    main()
