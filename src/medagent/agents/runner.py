"""Run one conversation turn and log what it cost (tokens, USD, latency). No content, no PII.

A turn is either a new user message or the answer to a pending confirmation (resume).
`stream_turn` yields live events (a step per finished node, then the final result); `run_turn`
just consumes it, so the CLI, the tests and the API share one code path.
"""

import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from medagent.agents.graph import AgentGraph
from medagent.guardrails.pii import pseudonymise
from medagent.observability.cost import RunCost, estimate_cost

log = structlog.get_logger("medagent.agents")


@dataclass(frozen=True)
class TurnResult:
    reply: str | None  # the assistant's message, or None if the graph paused for confirmation
    pending: dict[str, Any] | None  # the interrupt payload (e.g. the booking proposal)
    route: str
    cost: RunCost
    booking: dict[str, Any] | None = None  # appointment_id, doctor, start: this turn booked it
    doctors: list[dict[str, Any]] | None = None  # the bookable options this turn suggested

    @property
    def appointment_id(self) -> int | None:
        return int(self.booking["appointment_id"]) if self.booking else None

    @property
    def kind(self) -> str:
        """How a client should present the reply: emergency | harmful_intent | booked | normal."""
        if self.route in ("emergency", "harmful_intent"):
            return self.route
        return "booked" if self.appointment_id is not None else "normal"


@dataclass(frozen=True)
class StepEvent:
    node: str  # a graph node that has just started running


@dataclass(frozen=True)
class FinalEvent:
    result: TurnResult


TurnEvent = StepEvent | FinalEvent


def turn_config(thread_id: str, patient_id: int | None) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, "patient_id": patient_id}}


async def stream_turn(
    graph: AgentGraph,
    thread_id: str,
    patient_id: int | None,
    *,
    message: str | None = None,
    resume: object = None,
    on_cost: Callable[[RunCost], None] | None = None,
) -> AsyncIterator[TurnEvent]:
    """Run a turn, yielding a `StepEvent` as each node starts and a final `FinalEvent`.

    `on_cost` is called exactly once with the turn's token cost, even if the run fails midway
    (a failed LLM call can still be billed), so callers can meter spend.
    Consume the generator to the end (or cancel the task running it): the usage meter is bound
    to the task that iterates it.
    """
    if (message is None) == (resume is None):
        raise ValueError("pass exactly one of `message` or `resume`")
    config = turn_config(thread_id, patient_id)
    payload: Any = (
        Command(resume=resume) if resume is not None else {"messages": [HumanMessage(message)]}
    )

    started = time.perf_counter()
    usage_by_model: dict[str, Any] = {}
    try:
        with get_usage_metadata_callback() as usage:
            usage_by_model = usage.usage_metadata  # filled in as LLM calls finish
            # "tasks" mode reports each node when it STARTS (and again when it ends, with a
            # "result" key), which is what lets the UI show "Searching..." while it happens.
            async for chunk in graph.astream(payload, config, stream_mode="tasks"):
                if "result" not in chunk:
                    yield StepEvent(chunk["name"])
    finally:
        cost = estimate_cost(usage_by_model)
        if on_cost is not None:
            on_cost(cost)
    latency_ms = round((time.perf_counter() - started) * 1000)

    snapshot = await graph.aget_state(config)
    pending = snapshot.interrupts[0].value if snapshot.interrupts else None
    last = (snapshot.values.get("messages") or [None])[-1]
    reply = str(last.content) if pending is None and isinstance(last, AIMessage) else None
    route = str(snapshot.values.get("route") or "")

    log.info(
        "graph_run",
        thread=pseudonymise(thread_id),
        patient=pseudonymise(patient_id) if patient_id is not None else None,
        kind="resume" if resume is not None else "message",
        route=route,
        paused_for_confirmation=pending is not None,
        llm_calls_by_model=sorted(usage_by_model),
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        cache_read_tokens=cost.cache_read_tokens,
        est_cost_usd=cost.usd,
        unpriced_models=list(cost.unpriced_models) or None,
        latency_ms=latency_ms,
    )
    booking = snapshot.values.get("booking") if reply is not None else None
    # `doctor_options` is conversation memory; only the turn that suggested them shows them.
    suggested = snapshot.values.get("draft_kind") == "doctors" and reply is not None
    doctors = [dict(d) for d in snapshot.values.get("doctor_options") or []] if suggested else None
    yield FinalEvent(
        TurnResult(
            reply=reply,
            pending=pending,
            route=route,
            cost=cost,
            booking=dict(booking) if booking else None,
            doctors=doctors or None,
        )
    )


async def run_turn(
    graph: AgentGraph,
    thread_id: str,
    patient_id: int | None,
    *,
    message: str | None = None,
    resume: object = None,
) -> TurnResult:
    result: TurnResult | None = None
    async for event in stream_turn(graph, thread_id, patient_id, message=message, resume=resume):
        if isinstance(event, FinalEvent):
            result = event.result
    assert result is not None  # stream_turn always ends with a FinalEvent
    return result
