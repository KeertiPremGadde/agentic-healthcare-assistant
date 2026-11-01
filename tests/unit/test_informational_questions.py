"""General questions about a red-flag topic versus a live emergency (phrases in
informational_phrases.py).

"How can I recognise a stroke?" is a knowledge question: it is answered, with the safety notice in
front. A first-person pronoun alone no longer makes it an emergency. But the rule when in doubt is
to keep over-warning, so anything that says it is happening now ("I'm having", "my husband is",
"right now"), a second sentence or comma-joined clause, or a question about what to DO ("how do I
know if it is a heart attack?", "when should I worry") keeps the emergency reply."""

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from medagent.agents.deps import AgentDeps
from medagent.agents.graph import AgentGraph, build_graph
from medagent.agents.runner import run_turn
from medagent.agents.schemas import Route, RouteDecision
from medagent.guardrails.emergency import EMERGENCY_MESSAGE, SAFETY_NOTICE, detect_red_flag
from medagent.guardrails.screen import screen_message
from medagent.guardrails.texts import DE
from medagent.rag.answer import AnswerPayload
from tests.fakes import FakeAnswerLLM, FakeRetriever, FakeStructuredLLM, NoTools
from tests.unit.informational_phrases import (
    AMBIGUOUS_DE,
    AMBIGUOUS_EN,
    GENUINE_DE,
    GENUINE_EN,
    INFORMATIONAL_DE,
    INFORMATIONAL_EN,
)
from tests.unit.test_german_texts import _candidate


@pytest.mark.parametrize("phrase", INFORMATIONAL_EN + INFORMATIONAL_DE)
def test_a_general_question_is_answered_with_a_safety_notice(phrase: str) -> None:
    flag = detect_red_flag(phrase)
    assert flag is not None and flag.informational, "the notice must still be shown"
    assert screen_message(phrase) is None, "but it is not an emergency reply"


@pytest.mark.parametrize("phrase", GENUINE_EN + GENUINE_DE + AMBIGUOUS_EN + AMBIGUOUS_DE)
def test_anything_that_may_be_happening_keeps_the_emergency_reply(phrase: str) -> None:
    screen = screen_message(phrase)
    assert screen is not None and screen.kind == "emergency"


def test_the_language_of_an_unchanged_emergency_is_still_decided_by_the_rule() -> None:
    assert screen_message("I think I'm having a heart attack").language == "en"  # type: ignore[union-attr]
    assert screen_message("Ich glaube, ich habe einen Herzinfarkt").language == "de"  # type: ignore[union-attr]


# -- whole turns: the general question reaches the answer, the genuine one never does ---------


def _graph(llm: FakeStructuredLLM) -> AgentGraph:
    payload = AnswerPayload(
        answer="Face drooping and slurred speech are warning signs [MedlinePlus: Diabetes].",
        used_sources=[1],
        context_sufficient=True,
    )
    deps = AgentDeps(
        tools=NoTools(),  # type: ignore[arg-type]
        llm=llm,
        answer_llm=FakeAnswerLLM(payload),
        retriever=FakeRetriever([_candidate()]),
        session_factory=lambda: nullcontext(None),  # type: ignore[arg-type,return-value]
        clock=lambda: datetime(2026, 11, 2, 8, 0, tzinfo=UTC),
        tz=ZoneInfo("Europe/Berlin"),
        public_only=True,
        rag_min_score=0.7,
    )
    return build_graph(deps, InMemorySaver())


def _medical(language: str) -> RouteDecision:
    return RouteDecision(route=Route.MEDICAL_QUESTION, is_emergency=False, language=language)


def _thread() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


async def test_how_can_i_recognise_a_stroke_gets_the_answer_with_the_english_notice() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_medical("en")]})
    result = await run_turn(_graph(llm), _thread(), 1, message="How can I recognise a stroke?")
    reply = result.reply or ""
    assert reply.startswith(SAFETY_NOTICE + "\n\n")
    assert "[MedlinePlus: Diabetes]" in reply  # the answer follows
    assert EMERGENCY_MESSAGE not in reply
    assert llm.schemas_called == ["RouteDecision"]


async def test_wie_erkenne_ich_einen_schlaganfall_gets_the_answer_with_the_german_notice() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_medical("de")]})
    result = await run_turn(
        _graph(llm), _thread(), 1, message="Wie erkenne ich einen Schlaganfall?"
    )
    reply = result.reply or ""
    assert reply.startswith(DE.safety_notice + "\n\n")
    assert "Quellen:" in reply


@pytest.mark.parametrize(
    "message",
    [
        "I think I'm having a heart attack",
        "How do I know if I'm having a stroke? My face is drooping",
        "How do I know if it's a heart attack or heartburn?",
        "Ich glaube, ich habe einen Herzinfarkt",
    ],
)
async def test_a_possible_emergency_never_reaches_the_model(message: str) -> None:
    llm = FakeStructuredLLM()  # unscripted: any model call fails the test
    result = await run_turn(_graph(llm), _thread(), 1, message=message)
    assert result.route == "emergency"
    assert llm.calls == []
