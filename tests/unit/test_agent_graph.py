"""Graph behaviour without a database: routing, safety layers, output rules, cost logging."""

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from structlog.testing import capture_logs

from medagent.agents.deps import AgentDeps
from medagent.agents.graph import AgentGraph, build_graph
from medagent.agents.llm import LLMError
from medagent.agents.nodes.common import APOLOGY
from medagent.agents.nodes.output_guard import DOCTOR_NOTE, output_guard_node
from medagent.agents.nodes.respond import CAPABILITIES, OUT_OF_SCOPE
from medagent.agents.runner import run_turn
from medagent.agents.schemas import Route, RouteDecision
from medagent.guardrails.disclaimer import DISCLAIMER
from medagent.guardrails.emergency import EMERGENCY_MESSAGE, SAFETY_NOTICE
from medagent.observability.cost import estimate_cost
from medagent.rag.answer import NO_ANSWER, AnswerPayload
from medagent.rag.types import Candidate
from tests.fakes import FakeAnswerLLM, FakeRetriever, FakeStructuredLLM, no_database

BERLIN = ZoneInfo("Europe/Berlin")


def _candidate() -> Candidate:
    return Candidate(
        chunk_id=1,
        content="A stroke happens when blood flow to the brain stops. Signs: face drooping...",
        document_title="Stroke",
        source_key="medlineplus",
        url="https://medlineplus.gov/stroke.html",
        attribution="MedlinePlus - National Library of Medicine (medlineplus.gov)",
        page=None,
        vector_sim=0.85,
    )


def _graph(
    llm: FakeStructuredLLM, answer: AnswerPayload | None = None, *, db: bool = True
) -> AgentGraph:
    deps = AgentDeps(
        # The RAG node opens a session for the retriever; the fake retriever ignores it.
        session_factory=(lambda: nullcontext(None)) if db else no_database,  # type: ignore[arg-type,return-value]
        llm=llm,
        answer_llm=FakeAnswerLLM(
            answer
            or AnswerPayload(
                answer="Face drooping and slurred speech are warning signs [MedlinePlus: Stroke].",
                used_sources=[1],
                context_sufficient=True,
            )
        ),
        retriever=FakeRetriever([_candidate()]),
        clock=lambda: datetime(2026, 11, 2, 8, 0, tzinfo=UTC),
        tz=BERLIN,
        slot_minutes=30,
        public_only=True,
        rag_min_score=0.7,
    )
    return build_graph(deps, InMemorySaver())


def _route(route: Route, emergency: bool = False) -> RouteDecision:
    return RouteDecision(route=route, is_emergency=emergency)


def _thread() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


@pytest.mark.parametrize(
    "message",
    ["I have crushing chest pain and can't breathe", "Mein Vater ist bewusstlos"],
)
def test_emergency_short_circuits_without_any_llm_call(message: str) -> None:
    llm = FakeStructuredLLM()  # no script: any LLM call would fail the test
    result = run_turn(_graph(llm, db=False), _thread(), 1, message=message)
    assert result.reply == EMERGENCY_MESSAGE
    assert result.route == "emergency"
    assert llm.calls == []
    assert result.cost.usd == 0


def test_router_emergency_flag_is_the_second_safety_layer() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.MEDICAL_QUESTION, emergency=True)]})
    result = run_turn(_graph(llm), _thread(), 1, message="my husband looks very grey and sweaty")
    assert result.reply == EMERGENCY_MESSAGE
    assert llm.schemas_called == ["RouteDecision"]


def test_general_question_about_an_emergency_is_answered_with_a_safety_notice() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.MEDICAL_QUESTION)]})
    result = run_turn(_graph(llm), _thread(), 1, message="What are the warning signs of a stroke?")
    assert result.reply is not None
    assert result.reply.startswith(SAFETY_NOTICE)
    assert "[MedlinePlus: Stroke]" in result.reply
    assert "Sources:" in result.reply
    assert DISCLAIMER in result.reply


def test_medical_answer_without_evidence_says_dont_know() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.MEDICAL_QUESTION)]})
    weak = AnswerPayload(answer="x", used_sources=[1], context_sufficient=False)
    result = run_turn(_graph(llm, weak), _thread(), 1, message="What is a rare thing?")
    assert result.reply is not None
    assert result.reply.startswith(NO_ANSWER)
    assert DISCLAIMER in result.reply


@pytest.mark.parametrize(
    ("route", "expected"),
    [(Route.SMALLTALK, CAPABILITIES), (Route.OUT_OF_SCOPE, OUT_OF_SCOPE)],
)
def test_smalltalk_and_out_of_scope_use_fixed_replies(route: Route, expected: str) -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(route)]})
    result = run_turn(_graph(llm), _thread(), 1, message="hello")
    assert result.reply == expected
    assert llm.schemas_called == ["RouteDecision"]  # one cheap call, no second LLM call


def test_llm_failure_gives_an_apology_not_a_crash() -> None:
    llm = FakeStructuredLLM({RouteDecision: [LLMError("APIConnectionError")]})
    result = run_turn(_graph(llm), _thread(), 1, message="hello")
    assert result.reply == APOLOGY


def test_memory_persists_across_turns_in_a_thread() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.SMALLTALK), _route(Route.OUT_OF_SCOPE)]})
    graph, thread = _graph(llm), _thread()
    run_turn(graph, thread, 1, message="hi")
    run_turn(graph, thread, 1, message="what's the weather?")
    messages = graph.get_state({"configurable": {"thread_id": thread}}).values["messages"]
    assert [m.type for m in messages] == ["human", "ai", "human", "ai"]
    # the router saw the earlier turn as context on the second call
    assert len(llm.calls[1][2]) == 3


def test_output_guard_blocks_uncited_medical_text() -> None:
    update = output_guard_node({"draft": "Take 500 mg of X daily.", "draft_kind": "medical"})
    text = update["messages"][0].content
    assert text.startswith(NO_ANSWER)
    assert "500 mg" not in text
    assert DISCLAIMER in text


def test_output_guard_adds_doctor_note() -> None:
    update = output_guard_node({"draft": "A Cardiologist is advised.", "draft_kind": "doctors"})
    assert update["messages"][0].content.endswith(DOCTOR_NOTE)


def test_run_turn_requires_exactly_one_input() -> None:
    graph = _graph(FakeStructuredLLM())
    with pytest.raises(ValueError, match="exactly one"):
        run_turn(graph, _thread(), 1)
    with pytest.raises(ValueError, match="exactly one"):
        run_turn(graph, _thread(), 1, message="x", resume=True)


def test_run_log_has_cost_fields_and_no_message_text_or_raw_ids() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.SMALLTALK)]})
    secret_text = "my email is alex.example@example.com"
    with capture_logs() as logs:
        run_turn(_graph(llm), "thread-123", 42, message=secret_text)
    (entry,) = [e for e in logs if e["event"] == "graph_run"]
    assert {"est_cost_usd", "input_tokens", "output_tokens", "latency_ms"} <= entry.keys()
    flat = " ".join(str(v) for v in entry.values())
    assert "alex.example" not in flat
    assert "thread-123" not in flat
    assert entry["patient"] != "42"


def test_estimate_cost_uses_model_prices() -> None:
    usage = {
        "claude-haiku-5-5": {"input_tokens": 2_000_000, "output_tokens": 1_000_000},
        "claude-sonnet-5-5": {
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "input_token_details": {"cache_read": 500_000},
        },
        "some-new-model": {"input_tokens": 10, "output_tokens": 10},
    }
    cost = estimate_cost(usage)
    # haiku: 2*0.10 + 1*0.50 = 0.70; sonnet: 0.5M uncached*2 + 0.5M cached*0.20 = 1.10
    assert cost.usd == pytest.approx(1.80)
    assert cost.unpriced_models == ("some-new-model",)
    assert cost.cache_read_tokens == 500_000
