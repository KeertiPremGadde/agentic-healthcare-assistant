"""Last node of every turn: enforce the output rules in code, not in prompts.

- Fixed safety replies (emergency, harmful intent) pass through untouched.
- Medical answers must not contain a specific dose or quantity of a medicine (replaced by a
  referral to the doctor or pharmacist), must be cited or be the explicit "I don't know", and
  always carry the disclaimer.
- Doctor suggestions say they are not a diagnosis.
- General questions about emergencies get the safety notice in front.
"""

from typing import Any

from langchain_core.messages import AIMessage

from medagent.agents.nodes.common import APOLOGY
from medagent.agents.nodes.guardrail import FIXED_REPLY_ROUTES
from medagent.agents.state import AgentState
from medagent.guardrails.disclaimer import DISCLAIMER
from medagent.guardrails.dose import DOSE_REFERRAL, contains_dose
from medagent.guardrails.emergency import SAFETY_NOTICE
from medagent.rag.answer import NO_ANSWER
from medagent.tools.models import NearbyClinics

OSM_ATTRIBUTION = NearbyClinics.model_fields["attribution"].default

DOCTOR_NOTE = (
    "This suggestion is based on what you described and is not a diagnosis. If symptoms are "
    "severe or getting worse, seek urgent care."
)


def output_guard_node(state: AgentState) -> dict[str, Any]:
    draft = (state.get("draft") or "").strip() or APOLOGY
    kind = state.get("draft_kind", "")

    if kind in FIXED_REPLY_ROUTES:
        return {"messages": [AIMessage(content=draft)], "draft": ""}  # exactly as written

    if kind == "medical":
        if contains_dose(draft.replace(DISCLAIMER, "")):
            draft = DOSE_REFERRAL  # defence in depth: also enforced in answer_question
        elif "Sources:" not in draft and not draft.startswith((NO_ANSWER, DOSE_REFERRAL)):
            draft = NO_ANSWER  # never show uncited medical content (the fixed texts are exempt)
        if DISCLAIMER not in draft:
            draft = f"{draft}\n\n{DISCLAIMER}"
    elif kind == "doctors":
        draft = f"{draft}\n\n{DOCTOR_NOTE}"
    elif kind == "nearby" and OSM_ATTRIBUTION not in draft:
        draft = f"{draft}\n\n{OSM_ATTRIBUTION}"  # ODbL: attribution wherever the data appears

    if state.get("safety_notice"):
        draft = f"{SAFETY_NOTICE}\n\n{draft}"

    return {"messages": [AIMessage(content=draft)], "draft": ""}
