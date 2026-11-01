"""Supervisor: one structured-output call decides which specialist node handles the turn."""

from typing import Any

import structlog

from medagent.agents.deps import AgentDeps
from medagent.agents.llm import LLMError
from medagent.agents.nodes.common import APOLOGY, Node, recent_messages
from medagent.agents.nodes.guardrail import EMERGENCY, HARMFUL
from medagent.agents.prompts.router import ROUTER_SYSTEM_PROMPT
from medagent.agents.schemas import Route, RouteDecision
from medagent.agents.state import AgentState
from medagent.guardrails.emergency import EMERGENCY_MESSAGE
from medagent.guardrails.harmful import HARMFUL_MESSAGE
from medagent.guardrails.texts import reply_language

log = structlog.get_logger("medagent.agents")

ROUTE_TO_NODE = {
    Route.MEDICAL_QUESTION: "medical_rag",
    Route.FIND_DOCTOR: "doctor_finder",
    Route.BOOK: "booking",
    Route.CANCEL: "cancel",
    Route.NEARBY_CLINICS: "nearby_clinics",
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
    if appointments := state.get("appointment_options"):
        listed = ", ".join(
            f"{i}. {a['doctor_name']} {a['start_local']}" for i, a in enumerate(appointments, 1)
        )
        lines.append(f"The user's appointments listed earlier: {listed}")
    return "\n".join(lines) or "None."


def make_supervisor_node(deps: AgentDeps) -> Node:
    async def supervisor_node(state: AgentState) -> dict[str, Any]:
        try:
            decision = await deps.llm.ainvoke(
                RouteDecision,
                ROUTER_SYSTEM_PROMPT.format(context=_context(state)),
                recent_messages(state),
            )
        except LLMError as exc:
            log.warning("node_failed", node="supervisor", error=str(exc))
            return {"route": "error", "draft": APOLOGY, "draft_kind": "info"}
        # Second safety layer: phrasings the deterministic rules missed. An acute emergency
        # wins (call 112 now); otherwise harmful intent gets the fixed compassionate reply.
        if decision.is_emergency:
            log.warning("router_flagged", kind=EMERGENCY)
            return {"route": EMERGENCY, "draft": EMERGENCY_MESSAGE, "draft_kind": EMERGENCY}
        if decision.is_harmful:
            log.warning("router_flagged", kind=HARMFUL)
            return {"route": HARMFUL, "draft": HARMFUL_MESSAGE, "draft_kind": HARMFUL}
        # Set (or cleared) on every routed turn so an old query can never be reused. Retrieval
        # input only: the safety checks above have already run on the user's own words.
        query = (
            decision.english_search_query() if decision.route is Route.MEDICAL_QUESTION else None
        )
        return {
            "route": decision.route.value,
            "search_query_en": query or "",
            "reply_language": reply_language(decision.language),
        }

    return supervisor_node


def after_supervisor(state: AgentState) -> str:
    route = state.get("route", "")
    if route in (EMERGENCY, HARMFUL, "error"):
        return "output_guard"
    return ROUTE_TO_NODE[Route(route)]
