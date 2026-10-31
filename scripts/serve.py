"""Run the API: uv run python scripts/serve.py   ->  http://localhost:8000/docs

Why not just `uvicorn medagent.main:app`? On Windows uvicorn uses the proactor event loop, which
psycopg's async mode (the LangGraph checkpointer) rejects; this starts it on a selector loop
(`medagent.core.aio`). On Linux and macOS both ways are equivalent.
"""

import argparse
import asyncio

import uvicorn

from medagent.core.aio import app_loop_factory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # loop="none": uvicorn must not install its own loop; we choose it below.
    config = uvicorn.Config("medagent.main:app", host=args.host, port=args.port, loop="none")
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=app_loop_factory())


if __name__ == "__main__":
    main()
