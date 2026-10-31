"""Run one conversation turn and log what it cost (tokens, USD, latency). No content, no PII.

A turn is either a new user message or the answer to a pending confirmation (resume).
"""

import time
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


def turn_config(thread_id: str, patient_id: int | None) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, "patient_id": patient_id}}


def run_turn(
    graph: AgentGraph,
    thread_id: str,
    patient_id: int | None,
    *,
    message: str | None = None,
    resume: object = None,
) -> TurnResult:
    if (message is None) == (resume is None):
        raise ValueError("pass exactly one of `message` or `resume`")
    config = turn_config(thread_id, patient_id)
    payload: Any = (
        Command(resume=resume) if resume is not None else {"messages": [HumanMessage(message)]}
    )

    started = time.perf_counter()
    with get_usage_metadata_callback() as usage:
        values = graph.invoke(payload, config)
    latency_ms = round((time.perf_counter() - started) * 1000)

    snapshot = graph.get_state(config)
    pending = snapshot.interrupts[0].value if snapshot.interrupts else None
    last = (values.get("messages") or [None])[-1]
    reply = str(last.content) if pending is None and isinstance(last, AIMessage) else None
    cost = estimate_cost(usage.usage_metadata)
    route = str(values.get("route") or "")

    log.info(
        "graph_run",
        thread=pseudonymise(thread_id),
        patient=pseudonymise(patient_id) if patient_id is not None else None,
        kind="resume" if resume is not None else "message",
        route=route,
        paused_for_confirmation=pending is not None,
        llm_calls_by_model=sorted(usage.usage_metadata),
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        cache_read_tokens=cost.cache_read_tokens,
        est_cost_usd=cost.usd,
        unpriced_models=list(cost.unpriced_models) or None,
        latency_ms=latency_ms,
    )
    return TurnResult(reply=reply, pending=pending, route=route, cost=cost)
