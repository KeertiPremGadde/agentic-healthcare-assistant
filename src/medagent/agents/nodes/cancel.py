"""Cancelling an appointment: destructive, so it is confirmed with `interrupt()` like booking.

    cancel ──> confirm_cancel ──yes──> cancel_appointment
                     └──no──> "kept"

Only the logged-in patient's own upcoming appointments are listed or cancellable (the tool also
enforces this server-side).
"""

from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from medagent.agents.deps import AgentDeps
from medagent.agents.llm import LLMError
from medagent.agents.nodes.booking import is_yes, local_label
from medagent.agents.nodes.common import APOLOGY, ConfigNode, recent_messages
from medagent.agents.schemas import CancelRequest
from medagent.agents.state import AgentState, AppointmentOption
from medagent.tools.clinic import ToolError

log = structlog.get_logger("medagent.agents")

CANCEL_SYSTEM_PROMPT = """\
The user wants to cancel an appointment. Their upcoming appointments are listed below. If they \
clearly refer to one (by number, doctor or date), give its number; otherwise leave it empty.

{appointments}
"""
LOGIN_NEEDED = "I need to know who you are to manage appointments. Please log in first."


def _listing(options: list[AppointmentOption]) -> str:
    return "\n".join(
        f"{i}. {o['doctor_name']}, {o['start_local']}" for i, o in enumerate(options, 1)
    )


def make_cancel_node(deps: AgentDeps) -> ConfigNode:
    async def cancel_node(state: AgentState, config: RunnableConfig) -> Command[str]:
        patient_id = (config.get("configurable") or {}).get("patient_id")
        if patient_id is None:
            return Command(
                goto="output_guard", update={"draft": LOGIN_NEEDED, "draft_kind": "booking"}
            )
        try:
            upcoming = (await deps.tools.list_appointments(int(patient_id))).appointments
            options = [
                AppointmentOption(
                    id=a.id, doctor_name=a.doctor_name, start_local=local_label(a.start, deps)
                )
                for a in upcoming
            ]
            if not options:
                text = "You have no upcoming appointments to cancel."
                return Command(goto="output_guard", update={"draft": text, "draft_kind": "booking"})
            if len(options) == 1:
                chosen: AppointmentOption | None = options[0]  # nothing to choose: no LLM call
            else:
                request = await deps.llm.ainvoke(
                    CancelRequest,
                    CANCEL_SYSTEM_PROMPT.format(appointments=_listing(options)),
                    recent_messages(state),
                )
                n = request.appointment_option
                chosen = options[n - 1] if n and 1 <= n <= len(options) else None
        except (LLMError, ToolError) as exc:
            log.warning("node_failed", node="cancel", error=str(exc))
            return Command(goto="output_guard", update={"draft": APOLOGY, "draft_kind": "info"})

        if chosen is None:
            text = f"Which appointment would you like to cancel?\n{_listing(options)}"
            update = {"appointment_options": options, "draft": text, "draft_kind": "booking"}
            return Command(goto="output_guard", update=update)
        return Command(
            goto="confirm_cancel",
            update={"appointment_options": options, "cancel_proposal": chosen},
        )

    return cancel_node


def confirm_cancel_node(state: AgentState) -> Command[str]:
    chosen = state.get("cancel_proposal")
    if not chosen:
        update = {"draft": "There's nothing to cancel.", "draft_kind": "booking"}
        return Command(goto="output_guard", update=update)
    answer = interrupt(
        {
            "type": "confirm_cancel",
            "doctor": chosen["doctor_name"],
            "start": chosen["start_local"],
            "question": f"Cancel your appointment with {chosen['doctor_name']} on "
            f"{chosen['start_local']}?",
        }
    )
    if is_yes(answer):
        return Command(goto="cancel_appointment")
    kept: dict[str, Any] = {
        "cancel_proposal": None,
        "draft": "OK, I've kept your appointment.",
        "draft_kind": "booking",
    }
    return Command(goto="output_guard", update=kept)


def make_cancel_appointment_node(deps: AgentDeps) -> ConfigNode:
    async def cancel_appointment_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        chosen = state.get("cancel_proposal")
        done: dict[str, Any] = {
            "cancel_proposal": None,
            "appointment_options": [],
            "draft_kind": "booking",
        }
        patient_id = (config.get("configurable") or {}).get("patient_id")
        if not chosen or patient_id is None:
            return {**done, "draft": LOGIN_NEEDED if patient_id is None else "Nothing to cancel."}
        try:
            result = await deps.tools.cancel_appointment(int(patient_id), chosen["id"])
        except ToolError as exc:
            log.warning("node_failed", node="cancel_appointment", error=str(exc))
            return {**done, "draft": APOLOGY}
        if result.ok:
            ref = f"#A-{chosen['id']:04d}"
            text = f"Cancelled: {chosen['doctor_name']}, {chosen['start_local']} ({ref})."
        elif result.error == "not_cancellable":
            text = (
                "That appointment can no longer be cancelled "
                "(it has started or was already cancelled)."
            )
        else:
            text = "I couldn't find that appointment."
        return {**done, "draft": text}

    return cancel_appointment_node
