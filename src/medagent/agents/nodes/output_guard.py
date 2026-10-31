"""Last node of every turn: enforce the output rules in code, not in prompts.

- Medical answers must be cited or be the explicit "I don't know"; they always carry the disclaimer.
- Doctor suggestions say they are not a diagnosis.
- General questions about emergencies get the safety notice in front.
"""

from typing import Any

from langchain_core.messages import AIMessage

from medagent.agents.nodes.common import APOLOGY
from medagent.agents.nodes.guardrail import EMERGENCY
from medagent.agents.state import AgentState
from medagent.guardrails.disclaimer import DISCLAIMER
from medagent.guardrails.emergency import SAFETY_NOTICE
from medagent.rag.answer import NO_ANSWER

DOCTOR_NOTE = (
    "This suggestion is based on what you described and is not a diagnosis. If symptoms are "
    "severe or getting worse, seek urgent care."
)


def output_guard_node(state: AgentState) -> dict[str, Any]:
    draft = (state.get("draft") or "").strip() or APOLOGY
    kind = state.get("draft_kind", "")

    if kind == "medical":
        if "Sources:" not in draft and not draft.startswith(NO_ANSWER):
            draft = NO_ANSWER  # defence in depth: never show uncited medical content
        if DISCLAIMER not in draft:
            draft = f"{draft}\n\n{DISCLAIMER}"
    elif kind == "doctors":
        draft = f"{draft}\n\n{DOCTOR_NOTE}"

    if state.get("safety_notice") and kind != EMERGENCY:
        draft = f"{SAFETY_NOTICE}\n\n{draft}"

    return {"messages": [AIMessage(content=draft)], "draft": ""}
