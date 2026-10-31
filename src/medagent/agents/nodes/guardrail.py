"""First node of every turn: deterministic safety screen, no LLM call.

Order: harmful intent (lethal doses, how to kill/poison/harm someone: a fixed compassionate
reply that gives no information), then acute emergencies (fixed emergency reply). General
questions about emergencies are answered normally, with a safety notice in front.
"""

from typing import Any

import structlog

from medagent.agents.nodes.common import last_user_text
from medagent.agents.state import AgentState
from medagent.guardrails.emergency import detect_red_flag
from medagent.guardrails.screen import screen_message

EMERGENCY = "emergency"
HARMFUL = "harmful_intent"
FIXED_REPLY_ROUTES = (EMERGENCY, HARMFUL)  # routes whose reply is fixed text, never LLM output

log = structlog.get_logger("medagent.agents")


def guardrail_node(state: AgentState) -> dict[str, Any]:
    # Reset the per-turn fields so nothing leaks from the previous turn.
    update: dict[str, Any] = {
        "route": "",
        "draft": "",
        "draft_kind": "",
        "safety_notice": False,
        "appointment_id": None,
    }
    text = last_user_text(state)
    screen = screen_message(text)
    if screen is not None:
        # Category only: never the message, which may describe a person's crisis.
        log.warning("guardrail_triggered", kind=screen.kind, category=screen.category)
        return {**update, "route": screen.kind, "draft": screen.reply, "draft_kind": screen.kind}
    flag = detect_red_flag(text)
    if flag is not None and flag.informational:
        return {**update, "safety_notice": True}  # answer it, with a notice in front
    return update


def after_guardrail(state: AgentState) -> str:
    return "output_guard" if state.get("route") in FIXED_REPLY_ROUTES else "supervisor"
