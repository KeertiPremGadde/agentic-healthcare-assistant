"""Fixed replies for small talk and out-of-scope messages (no LLM call needed)."""

from typing import Any

from medagent.agents.schemas import Route
from medagent.agents.state import AgentState

CAPABILITIES = (
    "Hello! I'm MedAgent. I can answer general health questions with sources, suggest which kind "
    "of doctor to see for your symptoms, and book an appointment for you. What can I help with?"
)
OUT_OF_SCOPE = (
    "I can only help with health questions, finding the right doctor and booking appointments. "
    "Is there something in that area I can do for you?"
)


def respond_node(state: AgentState) -> dict[str, Any]:
    text = CAPABILITIES if state.get("route") == Route.SMALLTALK.value else OUT_OF_SCOPE
    return {"draft": text, "draft_kind": "info"}
