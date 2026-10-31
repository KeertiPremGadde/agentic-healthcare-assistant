"""First node of every turn: deterministic red-flag check, no LLM call."""

from typing import Any

from medagent.agents.nodes.common import last_user_text
from medagent.agents.state import AgentState
from medagent.guardrails.emergency import EMERGENCY_MESSAGE, detect_red_flag

EMERGENCY = "emergency"


def guardrail_node(state: AgentState) -> dict[str, Any]:
    # Reset the per-turn fields so nothing leaks from the previous turn.
    update: dict[str, Any] = {"route": "", "draft": "", "draft_kind": "", "safety_notice": False}
    flag = detect_red_flag(last_user_text(state))
    if flag is None:
        return update
    if flag.informational:
        return {**update, "safety_notice": True}  # answer it, with a notice in front
    return {**update, "route": EMERGENCY, "draft": EMERGENCY_MESSAGE, "draft_kind": EMERGENCY}


def after_guardrail(state: AgentState) -> str:
    return "output_guard" if state.get("route") == EMERGENCY else "supervisor"
