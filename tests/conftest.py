"""Tests marked `llm` call the real Anthropic API (they cost money), so they only run when
explicitly selected: `uv run pytest -m llm`. A plain `uv run pytest` skips them.

When they run, every LLM call in the session is metered and the total tokens and estimated cost
are printed at the end, so a model or prompt change shows its real price.
"""

import asyncio
import sys
from collections.abc import Callable, Iterator, Mapping

import pytest
from langchain_core.callbacks import get_usage_metadata_callback


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]] | None:
    """psycopg's async mode (the LangGraph checkpointer) needs a selector loop on Windows; the
    MCP client brings its own loop for subprocesses (see medagent/core/aio.py)."""
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return None


def _llm_selected(config: pytest.Config) -> bool:
    """True for `-m llm` (or e.g. `-m "llm and integration"`), false for `-m "not llm"`."""
    expr = config.getoption("-m") or ""
    return "llm" in expr and "not llm" not in expr


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _llm_selected(config):
        return
    skip = pytest.mark.skip(reason="real LLM call: run with `pytest -m llm`")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def llm_cost_report(request: pytest.FixtureRequest) -> Iterator[None]:
    if not _llm_selected(request.config):
        yield
        return
    from medagent.core.config import get_settings
    from medagent.observability.cost import estimate_cost

    with get_usage_metadata_callback() as usage:
        yield
    cost = estimate_cost(usage.usage_metadata)
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    lines = [
        f"LLM usage ({get_settings().llm_model}): {cost.input_tokens} input / "
        f"{cost.output_tokens} output tokens, estimated ${cost.usd:.4f}",
        *(f"  {model}: {dict(u)}" for model, u in sorted(usage.usage_metadata.items())),
    ]
    for line in lines:
        if reporter is not None:
            reporter.write_line(line)
        else:  # pragma: no cover
            print(line)
