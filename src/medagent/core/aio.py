"""Event-loop choices that differ on Windows.

On Windows, psycopg's async mode (used by the LangGraph checkpointer) needs a SelectorEventLoop,
but spawning subprocesses (the MCP stdio client) needs a ProactorEventLoop. Neither loop supports
both. So the app runs on a selector loop and the MCP client gets its own proactor loop in a
background thread (see `tools/mcp_client.py`). On Linux and macOS the default loop does both.
"""

import asyncio
import sys
from collections.abc import Callable, Coroutine
from typing import Any

IS_WINDOWS = sys.platform == "win32"


def app_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """Loop for the application (database, graph). None = asyncio's default."""
    return asyncio.SelectorEventLoop if IS_WINDOWS else None


def new_subprocess_loop() -> asyncio.AbstractEventLoop:
    """A loop that can spawn subprocesses on every OS."""
    if IS_WINDOWS:
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()


def run[R](main: Coroutine[Any, Any, R]) -> R:
    """`asyncio.run` with the right loop for the application on this OS."""
    return asyncio.run(main, loop_factory=app_loop_factory())
