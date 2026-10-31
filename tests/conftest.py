"""Tests marked `llm` call the real Anthropic API (they cost money), so they only run when
explicitly selected: `uv run pytest -m llm`. A plain `uv run pytest` skips them."""

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if "llm" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="real LLM call: run with `pytest -m llm`")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)
