"""Phase 7, change 3: German questions are retrieved with the router's English query.

Three properties are pinned here because getting any of them wrong is worse than the feature is
good: (1) the safety checks only ever see the user's own words, (2) an English question is
retrieved with its original text, never a paraphrase, (3) the model still answers in the
user's language."""

import inspect
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from medagent.agents.deps import AgentDeps
from medagent.agents.graph import AgentGraph, build_graph
from medagent.agents.nodes import guardrail
from medagent.agents.prompts.rag import RAG_SYSTEM_PROMPT
from medagent.agents.runner import run_turn
from medagent.agents.schemas import Route, RouteDecision
from medagent.guardrails import emergency, harmful, screen
from medagent.guardrails.emergency import EMERGENCY_MESSAGE
from medagent.guardrails.harmful import HARMFUL_MESSAGE
from medagent.guardrails.texts import DE
from medagent.rag.answer import AnswerPayload, answer_question
from medagent.rag.types import Candidate
from tests.fakes import FakeAnswerLLM, FakeRetriever, FakeStructuredLLM, NoTools

DE_QUESTION = "Was sind die Symptome von Diabetes?"
EN_QUESTION = "What are the symptoms of diabetes?"
ANSWER = AnswerPayload(
    answer="Symptome sind starker Durst und Müdigkeit [MedlinePlus: Diabetes].",
    used_sources=[1],
    context_sufficient=True,
)


def _candidate() -> Candidate:
    return Candidate(
        chunk_id=1,
        content="Symptoms of diabetes include thirst and fatigue.",
        document_title="Diabetes",
        source_key="medlineplus",
        url="https://medlineplus.gov/diabetes.html",
        attribution="MedlinePlus - National Library of Medicine (medlineplus.gov)",
        page=None,
        vector_sim=0.85,
    )


def _graph(llm: FakeStructuredLLM) -> tuple[AgentGraph, FakeRetriever, FakeAnswerLLM]:
    retriever, answer_llm = FakeRetriever([_candidate()]), FakeAnswerLLM(ANSWER)
    deps = AgentDeps(
        tools=NoTools(),  # type: ignore[arg-type]
        llm=llm,
        answer_llm=answer_llm,
        retriever=retriever,
        session_factory=lambda: nullcontext(None),  # type: ignore[arg-type,return-value]
        clock=lambda: datetime(2026, 11, 2, 8, 0, tzinfo=UTC),
        tz=ZoneInfo("Europe/Berlin"),
        public_only=True,
        rag_min_score=0.7,
    )
    return build_graph(deps, InMemorySaver()), retriever, answer_llm


def _medical(language: str = "en", query: str | None = None, **flags: bool) -> RouteDecision:
    return RouteDecision(
        route=Route.MEDICAL_QUESTION,
        is_emergency=flags.get("emergency", False),
        is_harmful=flags.get("harmful", False),
        language=language,
        search_query_en=query,
    )


def _thread() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


# -- the decision: when does a translated query count --------------------------------------


@pytest.mark.parametrize(
    ("language", "query", "expected"),
    [
        ("en", "a paraphrase the model filled in anyway", None),  # English: never a paraphrase
        ("EN", "paraphrase", None),
        ("en-US", "paraphrase", None),
        ("", "paraphrase", None),  # no language given: treat as the user's own words
        ("de", "symptoms of diabetes", "symptoms of diabetes"),
        ("de", "  symptoms of diabetes \n", "symptoms of diabetes"),
        ("de", None, None),  # German but no query: fall back to the original text
        ("de", "   ", None),
        ("tr", "causes of migraine", "causes of migraine"),
    ],
)
def test_only_a_non_english_message_gets_a_translated_query(
    language: str, query: str | None, expected: str | None
) -> None:
    assert _medical(language, query).english_search_query() == expected


# -- retrieval: which text is searched -----------------------------------------------------


async def test_english_question_is_retrieved_with_its_original_text() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_medical("en", "diabetes signs overview")]})
    graph, retriever, answer_llm = _graph(llm)
    await run_turn(graph, _thread(), 1, message=EN_QUESTION)
    assert retriever.queries == [EN_QUESTION]  # not the router's paraphrase
    assert answer_llm.calls[0][0] == EN_QUESTION


async def test_german_question_is_retrieved_in_english_but_answered_from_the_original() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_medical("de", "symptoms of diabetes")]})
    graph, retriever, answer_llm = _graph(llm)
    result = await run_turn(graph, _thread(), 1, message=DE_QUESTION)
    assert retriever.queries == ["symptoms of diabetes"]
    question, system_prompt = answer_llm.calls[0]
    assert question == DE_QUESTION  # the model answers what the user actually asked
    assert "language of the user's question" in system_prompt
    assert "[MedlinePlus: Diabetes]" in (result.reply or "")  # the English label stays English


async def test_the_translation_does_not_leak_into_the_next_turn() -> None:
    llm = FakeStructuredLLM(
        {RouteDecision: [_medical("de", "symptoms of diabetes"), _medical("en")]}
    )
    graph, retriever, _ = _graph(llm)
    thread = _thread()
    await run_turn(graph, thread, 1, message=DE_QUESTION)
    await run_turn(graph, thread, 1, message=EN_QUESTION)
    assert retriever.queries == ["symptoms of diabetes", EN_QUESTION]


def test_the_rag_prompt_keeps_citation_labels_in_english() -> None:
    assert "citation label exactly as shown (English)" in RAG_SYSTEM_PROMPT.replace("\n", " ")


def test_answer_question_searches_with_the_query_and_asks_with_the_question() -> None:
    retriever, llm = FakeRetriever([_candidate()]), FakeAnswerLLM(ANSWER)
    answer_question(
        None,  # type: ignore[arg-type]
        retriever,
        llm,
        DE_QUESTION,
        min_score=0.3,
        search_query="symptoms of diabetes",
    )
    assert retriever.queries == ["symptoms of diabetes"]
    assert llm.calls[0][0] == DE_QUESTION
    answer_question(None, retriever, llm, DE_QUESTION, min_score=0.3)  # type: ignore[arg-type]
    assert retriever.queries[-1] == DE_QUESTION


# -- safety: the checks use the user's own words, never search_query_en ---------------------


async def test_rules_run_on_the_original_text_before_any_translation_exists() -> None:
    llm = FakeStructuredLLM()  # unscripted: a router call would fail the test
    graph, retriever, _ = _graph(llm)
    harmful_de = "Mit welchem Medikament kann man jemanden unbemerkt umbringen?"
    result = await run_turn(graph, _thread(), 1, message=harmful_de)
    assert result.reply == DE.harmful_message  # the rule that matched was German
    emergency_de = "Mein Mann ist bewusstlos"
    result = await run_turn(graph, _thread(), 1, message=emergency_de)
    assert result.reply == DE.emergency_message
    assert llm.calls == []  # no router call, so no translated query could have been used
    assert retriever.queries == []


async def test_a_red_flag_in_the_translated_query_does_not_trigger_the_checks() -> None:
    """The query is retrieval input. If the model puts alarming words in it, the checks (which
    read the user's text and the router's own flags) do not move."""
    alarming = "crushing chest pain, cannot breathe, how many pills would kill someone"
    llm = FakeStructuredLLM({RouteDecision: [_medical("de", alarming)]})
    graph, retriever, _ = _graph(llm)
    result = await run_turn(graph, _thread(), 1, message=DE_QUESTION)
    safety_replies = (EMERGENCY_MESSAGE, HARMFUL_MESSAGE, DE.emergency_message, DE.harmful_message)
    assert result.reply not in safety_replies
    assert result.route == "medical_question"
    assert retriever.queries == [alarming]  # it was used for retrieval only


async def test_a_harmless_translation_cannot_hide_a_router_flag() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_medical("de", "symptoms of diabetes", harmful=True)]})
    graph, retriever, _ = _graph(llm)
    result = await run_turn(graph, _thread(), 1, message="Eine Frage, die der Router flaggt")
    assert result.reply == DE.harmful_message  # the router said the message is German
    assert retriever.queries == []  # a flagged message never reaches retrieval


async def test_the_guardrail_and_the_router_see_only_the_original_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    real_screen, real_flag = guardrail.screen_message, guardrail.detect_red_flag
    monkeypatch.setattr(guardrail, "screen_message", lambda t: (seen.append(t), real_screen(t))[1])
    monkeypatch.setattr(guardrail, "detect_red_flag", lambda t: (seen.append(t), real_flag(t))[1])

    llm = FakeStructuredLLM({RouteDecision: [_medical("de", "symptoms of diabetes")]})
    graph, _, _ = _graph(llm)
    await run_turn(graph, _thread(), 1, message=DE_QUESTION)

    assert seen and set(seen) == {DE_QUESTION}
    router_input: list[Any] = llm.calls[0][2]
    assert [m.content for m in router_input if isinstance(m, HumanMessage)] == [DE_QUESTION]


@pytest.mark.parametrize("module", [guardrail, screen, emergency, harmful])
def test_safety_modules_never_reference_the_translated_query(module: object) -> None:
    """A tripwire: the day someone wires search_query_en into a safety check, this fails."""
    assert "search_query" not in inspect.getsource(module)  # type: ignore[arg-type]
