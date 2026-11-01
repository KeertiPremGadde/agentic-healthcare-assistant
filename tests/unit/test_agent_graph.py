"""Graph behaviour without a database: routing, safety layers, output rules, cost logging."""

import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.checkpoint.memory import InMemorySaver
from structlog.testing import capture_logs

from medagent.agents.deps import AgentDeps
from medagent.agents.graph import AgentGraph, build_graph
from medagent.agents.llm import LLMError
from medagent.agents.nodes.output_guard import DOCTOR_NOTE, OSM_ATTRIBUTION, output_guard_node
from medagent.agents.nodes.respond import CAPABILITIES, OUT_OF_SCOPE
from medagent.agents.runner import run_turn
from medagent.agents.schemas import Route, RouteDecision
from medagent.guardrails.disclaimer import DISCLAIMER
from medagent.guardrails.dose import DOSE_REFERRAL
from medagent.guardrails.emergency import EMERGENCY_MESSAGE, SAFETY_NOTICE
from medagent.guardrails.texts import DE, ROUTER_FAILURE_MESSAGE
from medagent.observability.cost import estimate_cost
from medagent.observability.tracing import TraceContext
from medagent.rag.answer import NO_ANSWER, AnswerPayload
from medagent.rag.types import Candidate
from tests.fakes import FakeAnswerLLM, FakeRetriever, FakeStructuredLLM, NoTools, no_database

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
        tools=NoTools(),  # type: ignore[arg-type]  (these tests never schedule anything)
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
        # The RAG node opens a session for the retriever; the fake retriever ignores it.
        session_factory=(lambda: nullcontext(None)) if db else no_database,  # type: ignore[arg-type,return-value]
        clock=lambda: datetime(2026, 11, 2, 8, 0, tzinfo=UTC),
        tz=BERLIN,
        public_only=True,
        rag_min_score=0.7,
    )
    return build_graph(deps, InMemorySaver())


def _route(route: Route, emergency: bool = False) -> RouteDecision:
    return RouteDecision(route=route, is_emergency=emergency)


def _thread() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("I have crushing chest pain and can't breathe", EMERGENCY_MESSAGE),
        ("Mein Vater ist bewusstlos", DE.emergency_message),  # the rule's language: German
    ],
)
async def test_emergency_short_circuits_without_any_llm_call(message: str, expected: str) -> None:
    llm = FakeStructuredLLM()  # no script: any LLM call would fail the test
    result = await run_turn(_graph(llm, db=False), _thread(), 1, message=message)
    assert result.reply == expected
    assert result.route == "emergency"
    assert llm.calls == []
    assert result.cost.usd == 0


async def test_router_emergency_flag_is_the_second_safety_layer() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.MEDICAL_QUESTION, emergency=True)]})
    result = await run_turn(_graph(llm), _thread(), 1, message="my husband looks grey and sweaty")
    assert result.reply == EMERGENCY_MESSAGE
    assert llm.schemas_called == ["RouteDecision"]


async def test_general_question_about_an_emergency_is_answered_with_a_safety_notice() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.MEDICAL_QUESTION)]})
    result = await run_turn(
        _graph(llm), _thread(), 1, message="What are the warning signs of a stroke?"
    )
    assert result.reply is not None
    assert result.reply.startswith(SAFETY_NOTICE)
    assert "[MedlinePlus: Stroke]" in result.reply
    assert "Sources:" in result.reply
    assert DISCLAIMER in result.reply


async def test_medical_answer_without_evidence_says_dont_know() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.MEDICAL_QUESTION)]})
    weak = AnswerPayload(answer="x", used_sources=[1], context_sufficient=False)
    result = await run_turn(_graph(llm, weak), _thread(), 1, message="What is a rare thing?")
    assert result.reply is not None
    assert result.reply.startswith(NO_ANSWER)
    assert DISCLAIMER in result.reply


@pytest.mark.parametrize(
    ("route", "expected"),
    [(Route.SMALLTALK, CAPABILITIES), (Route.OUT_OF_SCOPE, OUT_OF_SCOPE)],
)
async def test_smalltalk_and_out_of_scope_use_fixed_replies(route: Route, expected: str) -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(route)]})
    result = await run_turn(_graph(llm), _thread(), 1, message="hello")
    assert result.reply == expected
    assert llm.schemas_called == ["RouteDecision"]  # one cheap call, no second LLM call


async def test_router_failure_gives_a_neutral_reply_with_the_emergency_lines() -> None:
    llm = FakeStructuredLLM({RouteDecision: [LLMError("APIConnectionError", "api")]})
    result = await run_turn(_graph(llm), _thread(), 1, message="hello")
    assert result.reply == ROUTER_FAILURE_MESSAGE
    # neutral, not a refusal; both languages; the emergency and crisis lines are always there
    for needle in ("rephrase", "formulieren Sie", "112", "0800 111 0 111", "988"):
        assert needle in ROUTER_FAILURE_MESSAGE
    assert "can't help" not in ROUTER_FAILURE_MESSAGE


@pytest.mark.parametrize("kind", ["parse", "api", "other"])
async def test_router_failure_logs_its_kind_without_user_text(kind: str) -> None:
    llm = FakeStructuredLLM({RouteDecision: [LLMError("boom during RouteDecision", kind)]})
    with capture_logs() as logs:
        await run_turn(_graph(llm), _thread(), 1, message="a secret sentence")
    failed = [e for e in logs if e["event"] == "node_failed" and e["node"] == "supervisor"]
    assert [e["kind"] for e in failed] == [kind]
    assert "secret" not in str(logs)


async def test_memory_persists_across_turns_in_a_thread() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.SMALLTALK), _route(Route.OUT_OF_SCOPE)]})
    graph, thread = _graph(llm), _thread()
    await run_turn(graph, thread, 1, message="hi")
    await run_turn(graph, thread, 1, message="what's the weather?")
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread}})
    assert [m.type for m in snapshot.values["messages"]] == ["human", "ai", "human", "ai"]
    assert len(llm.calls[1][2]) == 3  # the router saw the earlier turn as context


def test_output_guard_blocks_uncited_medical_text() -> None:
    update = output_guard_node(
        {"draft": "Leafy greens are good for you every day.", "draft_kind": "medical"}
    )
    text = update["messages"][0].content
    assert text.startswith(NO_ANSWER)
    assert "leafy greens" not in text.lower()
    assert DISCLAIMER in text


def test_output_guard_replaces_a_dose_even_when_it_is_also_uncited() -> None:
    update = output_guard_node({"draft": "Take 500 mg of X daily.", "draft_kind": "medical"})
    text = update["messages"][0].content
    assert text.startswith(DOSE_REFERRAL)  # the dose rule wins: the number must never be shown
    assert "500" not in text
    assert DISCLAIMER in text


def test_output_guard_keeps_the_fixed_dose_referral_and_idk_texts_as_they_are() -> None:
    for fixed in (DOSE_REFERRAL, NO_ANSWER):
        text = output_guard_node({"draft": fixed, "draft_kind": "medical"})["messages"][0].content
        assert text.startswith(fixed)  # not overwritten for lacking a Sources section
        assert DISCLAIMER in text


def test_output_guard_passes_fixed_safety_replies_through_untouched() -> None:
    from medagent.guardrails.harmful import HARMFUL_MESSAGE

    for reply, kind in ((HARMFUL_MESSAGE, "harmful_intent"), (EMERGENCY_MESSAGE, "emergency")):
        state = {"draft": reply, "draft_kind": kind, "safety_notice": True}
        assert output_guard_node(state)["messages"][0].content == reply  # no notice, no disclaimer


def test_output_guard_adds_doctor_note() -> None:
    update = output_guard_node({"draft": "A Cardiologist is advised.", "draft_kind": "doctors"})
    assert update["messages"][0].content.endswith(DOCTOR_NOTE)


def test_output_guard_enforces_openstreetmap_attribution() -> None:
    update = output_guard_node({"draft": "1. Some Hospital", "draft_kind": "nearby"})
    assert update["messages"][0].content.endswith(OSM_ATTRIBUTION)


async def test_run_turn_requires_exactly_one_input() -> None:
    graph = _graph(FakeStructuredLLM())
    with pytest.raises(ValueError, match="exactly one"):
        await run_turn(graph, _thread(), 1)
    with pytest.raises(ValueError, match="exactly one"):
        await run_turn(graph, _thread(), 1, message="x", resume=True)


async def test_run_log_has_cost_fields_and_no_message_text_or_raw_ids() -> None:
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.SMALLTALK)]})
    secret_text = "my email is alex.example@example.com"
    with capture_logs() as logs:
        await run_turn(_graph(llm), "thread-123", 42, message=secret_text)
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


async def test_stream_turn_reports_cost_exactly_once_even_when_the_run_fails() -> None:
    from medagent.agents.runner import stream_turn
    from medagent.observability.cost import RunCost

    class Exploding(FakeStructuredLLM):
        async def ainvoke(self, schema, system, messages):  # type: ignore[no-untyped-def]
            raise RuntimeError("provider blew up")

    seen: list[RunCost] = []
    stream = stream_turn(_graph(Exploding()), _thread(), 1, message="hello", on_cost=seen.append)
    with pytest.raises(RuntimeError, match="provider blew up"):
        async for _ in stream:
            pass
    assert len(seen) == 1  # a failed LLM call can still be billed, so it is metered


async def test_stream_turn_yields_steps_as_nodes_start_then_one_final_event() -> None:
    from medagent.agents.runner import FinalEvent, StepEvent, stream_turn

    llm = FakeStructuredLLM({RouteDecision: [_route(Route.SMALLTALK)]})
    events = [e async for e in stream_turn(_graph(llm), _thread(), 1, message="hello")]
    steps = [e.node for e in events if isinstance(e, StepEvent)]
    assert steps == ["guardrail", "supervisor", "respond", "output_guard"]
    assert isinstance(events[-1], FinalEvent)
    assert sum(isinstance(e, FinalEvent) for e in events) == 1
    assert events[-1].result.reply == CAPABILITIES


# ------------------------------------------------------------------ tracing


class _RecordingHandler(BaseCallbackHandler):
    """Stands in for the Langfuse handler: records which graph nodes started."""

    def __init__(self) -> None:
        self.nodes: list[str] = []

    def on_chain_start(self, serialized: Any, inputs: Any, **kwargs: Any) -> None:
        node = (kwargs.get("metadata") or {}).get("langgraph_node")
        if node and node not in self.nodes:
            self.nodes.append(node)


class _RecordingTrace:
    def __init__(self, tracer: "_RecordingTracer") -> None:
        self._tracer = tracer
        self.callbacks: list[BaseCallbackHandler] = [tracer.handler]
        self.metadata = tracer.metadata

    def finish(self, **kwargs: Any) -> None:
        self._tracer.finished.append(kwargs)


class _RecordingTracer:
    def __init__(self) -> None:
        self.handler = _RecordingHandler()
        self.started: list[tuple[TraceContext | None, str]] = []
        self.finished: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {"langfuse_session_id": "conv-1"}

    def start(self, context: TraceContext | None, *, kind: str) -> Any:
        self.started.append((context, kind))
        return _RecordingTrace(self)

    def shutdown(self) -> None:
        return None


async def test_a_turn_is_traced_node_by_node_and_scored_at_the_end() -> None:
    tracer = _RecordingTracer()
    llm = FakeStructuredLLM({RouteDecision: [_route(Route.MEDICAL_QUESTION)]})
    context = TraceContext(session_id="conv-1", user_id="abc", tags=("api",))
    result = await run_turn(
        _graph(llm), _thread(), 1, message="What is a stroke?", tracer=tracer, trace=context
    )
    assert tracer.started == [(context, "message")]
    assert tracer.handler.nodes[:2] == ["guardrail", "supervisor"]
    assert "medical_rag" in tracer.handler.nodes
    assert "output_guard" in tracer.handler.nodes
    (finished,) = tracer.finished
    assert finished["route"] == Route.MEDICAL_QUESTION.value
    assert finished["kind"] == "normal"
    assert finished["paused"] is False
    assert finished["usd"] == result.cost.usd


async def test_tracing_changes_nothing_about_the_answer() -> None:
    def scripted() -> FakeStructuredLLM:
        return FakeStructuredLLM({RouteDecision: [_route(Route.SMALLTALK)]})

    plain = await run_turn(_graph(scripted()), _thread(), 1, message="hi")
    traced = await run_turn(
        _graph(scripted()), _thread(), 1, message="hi", tracer=_RecordingTracer()
    )
    assert traced.reply == plain.reply
    assert traced.route == plain.route


async def test_an_emergency_turn_is_traced_with_its_kind() -> None:
    tracer = _RecordingTracer()
    llm = FakeStructuredLLM()  # no LLM call is scripted: the rules answer
    result = await run_turn(
        _graph(llm), _thread(), 1, message="I have crushing chest pain", tracer=tracer
    )
    assert result.reply == EMERGENCY_MESSAGE
    (finished,) = tracer.finished
    assert finished["kind"] == "emergency"
    assert finished["route"] == "emergency"
