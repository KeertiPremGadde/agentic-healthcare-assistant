"""The router's second safety layer, on the real model. Run with: uv run pytest -m llm

The rules catch the canonical phrasings (unit tests). This checks the part only a model can do:
flag the euphemisms the rules cannot match, without flagging ordinary medicine questions.
Router calls are non-deterministic: a failure here is a signal to look at the router prompt, not
proof of a code bug. `scripts/redteam_report.py` prints the full rules-vs-router comparison.
"""

import asyncio

import pytest
from langchain_core.messages import HumanMessage

from medagent.agents.llm import AnthropicStructuredLLM
from medagent.agents.prompts.router import ROUTER_SYSTEM_PROMPT
from medagent.agents.schemas import RouteDecision
from medagent.core.config import get_settings
from tests.unit.test_harmful_and_dose import BENIGN_LOOK_ALIKES, KNOWN_GAPS

pytestmark = [pytest.mark.integration, pytest.mark.llm]


@pytest.fixture(scope="module")
def llm() -> AnthropicStructuredLLM:
    if get_settings().anthropic_api_key is None:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return AnthropicStructuredLLM()


async def _decisions(llm: AnthropicStructuredLLM, texts: list[str]) -> list[RouteDecision]:
    gate = asyncio.Semaphore(5)

    async def one(text: str) -> RouteDecision:
        async with gate:
            return await llm.ainvoke(
                RouteDecision, ROUTER_SYSTEM_PROMPT.format(context="None."), [HumanMessage(text)]
            )

    return list(await asyncio.gather(*(one(t) for t in texts)))


async def test_router_flags_the_euphemisms_the_rules_cannot_match(
    llm: AnthropicStructuredLLM,
) -> None:
    decisions = await _decisions(llm, KNOWN_GAPS)
    missed = [
        t
        for t, d in zip(KNOWN_GAPS, decisions, strict=True)
        if not (d.is_harmful or d.is_emergency)
    ]
    assert not missed, f"router did not flag: {missed}"


async def test_router_does_not_flag_ordinary_medicine_questions_as_harmful(
    llm: AnthropicStructuredLLM,
) -> None:
    decisions = await _decisions(llm, BENIGN_LOOK_ALIKES)
    flagged = [t for t, d in zip(BENIGN_LOOK_ALIKES, decisions, strict=True) if d.is_harmful]
    assert not flagged, f"router over-blocked: {flagged}"
