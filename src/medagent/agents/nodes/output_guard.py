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
from medagent.guardrails.dose import contains_dose
from medagent.guardrails.texts import ALL_TEXTS, texts_for
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
        # A reply is checked against the fixed texts of every language (the model may answer in
        # any); what the guard adds itself is in the language of the turn.
        texts = texts_for(state.get("reply_language"))
        without_disclaimers = draft
        for t in ALL_TEXTS:
            without_disclaimers = without_disclaimers.replace(t.disclaimer, "")
        fixed_replies = tuple(r for t in ALL_TEXTS for r in (t.no_answer, t.dose_referral))
        if contains_dose(without_disclaimers):
            draft = texts.dose_referral  # defence in depth: also enforced in answer_question
        elif not any(t.sources_label in draft for t in ALL_TEXTS) and not draft.startswith(
            fixed_replies
        ):
            draft = texts.no_answer  # never show uncited medical content (fixed texts exempt)
        if not any(t.disclaimer in draft for t in ALL_TEXTS):
            draft = f"{draft}\n\n{texts.disclaimer}"
    elif kind == "doctors":
        draft = f"{draft}\n\n{DOCTOR_NOTE}"
    elif kind == "nearby" and OSM_ATTRIBUTION not in draft:
        draft = f"{draft}\n\n{OSM_ATTRIBUTION}"  # ODbL: attribution wherever the data appears

    if state.get("safety_notice"):
        notice = texts_for(state.get("reply_language")).safety_notice
        draft = f"{notice}\n\n{draft}"

    return {"messages": [AIMessage(content=draft)], "draft": ""}
