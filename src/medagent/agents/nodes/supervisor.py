"""Supervisor: one structured-output call decides which specialist node handles the turn."""

from typing import Any

import structlog

from medagent.agents.deps import AgentDeps
from medagent.agents.llm import LLMError
from medagent.agents.nodes.common import APOLOGY, Node, recent_messages
from medagent.agents.nodes.guardrail import EMERGENCY
from medagent.agents.prompts.router import ROUTER_SYSTEM_PROMPT
from medagent.agents.schemas import Route, RouteDecision
from medagent.agents.state import AgentState
from medagent.guardrails.emergency import EMERGENCY_MESSAGE

log = structlog.get_logger("medagent.agents")

ROUTE_TO_NODE = {
    Route.MEDICAL_QUESTION: "medical_rag",
    Route.FIND_DOCTOR: "doctor_finder",
    Route.BOOK: "booking",
    Route.SMALLTALK: "respond",
    Route.OUT_OF_SCOPE: "respond",
}


def _context(state: AgentState) -> str:
    lines = []
    if options := state.get("doctor_options"):
        names = ", ".join(f"{i}. {o['name']} ({o['specialty']})" for i, o in enumerate(options, 1))
        lines.append(f"Doctors suggested earlier: {names}")
    if state.get("booking_doctor_id"):
        lines.append("A booking is in progress.")
    return "\n".join(lines) or "None."


def make_supervisor_node(deps: AgentDeps) -> Node:
    def supervisor_node(state: AgentState) -> dict[str, Any]:
        try:
            decision = deps.llm.invoke(
                RouteDecision,
                ROUTER_SYSTEM_PROMPT.format(context=_context(state)),
                recent_messages(state),
            )
        except LLMError as exc:
            log.warning("node_failed", node="supervisor", error=str(exc))
            return {"route": "error", "draft": APOLOGY, "draft_kind": "info"}
        if decision.is_emergency:  # second safety layer: phrasings the rules missed
            return {"route": EMERGENCY, "draft": EMERGENCY_MESSAGE, "draft_kind": EMERGENCY}
        return {"route": decision.route.value}

    return supervisor_node


def after_supervisor(state: AgentState) -> str:
    route = state.get("route", "")
    if route in (EMERGENCY, "error"):
        return "output_guard"
    return ROUTE_TO_NODE[Route(route)]
