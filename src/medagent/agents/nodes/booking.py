"""Booking with human-in-the-loop confirmation, through the clinic tools (MCP by default).

    booking ──> confirm ──yes──> book_appointment
                   └──no──> (ask for another day/time)

`confirm` calls `interrupt()`: the graph stops, the state is checkpointed, and the caller shows
the proposal. On resume LangGraph re-runs the interrupted node *from the start*, so `confirm`
has no side effects at all; the write happens in `book_appointment`, whose tool re-validates.
"""

from datetime import UTC, date, datetime, time
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from medagent.agents.deps import AgentDeps
from medagent.agents.llm import LLMError
from medagent.agents.nodes.common import APOLOGY, ConfigNode, Node, recent_messages
from medagent.agents.prompts.booking import BOOKING_SYSTEM_PROMPT
from medagent.agents.schemas import BookingRequest
from medagent.agents.state import AgentState, DoctorOption, Proposal
from medagent.tools.clinic import ClinicTools, ToolError
from medagent.tools.models import DoctorInfo

log = structlog.get_logger("medagent.agents")

SEARCH_DAYS = 14
ERROR_TEXT = {
    "in_the_past": "That time has already passed.",
    "not_a_working_day": "{doctor} doesn't work on that day.",
    "outside_working_hours": "That time isn't one of {doctor}'s appointment slots.",
    "already_booked": "That time is already booked.",
    "unknown_doctor": "I couldn't find that doctor any more.",
}
YES = frozenset({"yes", "y", "ja", "j", "confirm"})  # explicit tokens only, not free-text parsing


def day_label(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b %Y}"


def closed_text(doctor: str, day: date | None, holiday: str | None) -> str:
    """ "Dr. X's practice is closed on Fri 31 Oct 2025 (Reformation Day)." (no trailing space)"""
    on = f" on {day_label(day)}" if day else ""
    name = f" ({holiday})" if holiday else ""
    return f"{doctor}'s practice is closed{on}{name}."


def error_text(
    code: str | None, doctor: str, day: date | None = None, detail: str | None = None
) -> str:
    """User-facing reason for a booking error code (`detail` = the holiday's name, if any)."""
    if code == "public_holiday":
        return closed_text(doctor, day, detail)
    return ERROR_TEXT.get(code or "", "That time can't be booked.").format(doctor=doctor)


def local_label(start: datetime, deps: AgentDeps) -> str:
    local = start.astimezone(deps.tz)
    return f"{local:%a} {local.day} {local:%b %Y}, {local:%H:%M}"


def is_yes(answer: object) -> bool:
    """The UI sends a structured answer (bool or {"confirmed": bool}); the CLI may send y/n."""
    if isinstance(answer, bool):
        return answer
    if isinstance(answer, dict):
        return answer.get("confirmed") is True
    if isinstance(answer, str):
        return answer.strip().lower() in YES
    return False


def _why_not_that_day(
    doctor: str,
    day: date,
    time_of_day: str | None,
    works_that_weekday: bool,
    holiday: str | None = None,
) -> str:
    """Why the requested day can't be booked, when we are offering a different day instead.

    In order: no working hours that weekday (a day off), a public holiday (the practice is
    closed), otherwise the day simply has no matching free slot."""
    if not works_that_weekday:
        return f"{doctor} doesn't work on {day:%A}s. "
    if holiday:
        return closed_text(doctor, day, holiday) + " "
    when = f"{time_of_day} " if time_of_day else ""
    return f"{doctor} has no free {when}slot on that day. "


def _options_text(options: list[DoctorOption]) -> str:
    lines = [f"{i}. {o['name']} ({o['specialty']})" for i, o in enumerate(options, 1)]
    return "\n".join(lines) or "None."


def _as_option(d: DoctorInfo) -> DoctorOption:
    return DoctorOption(
        id=d.id, name=d.name, specialty=d.specialty, city=d.city, languages=d.languages
    )


async def _resolve_doctor(
    tools: ClinicTools, request: BookingRequest, state: AgentState
) -> tuple[DoctorInfo | None, str | None, list[DoctorOption] | None]:
    """Return (doctor, question_for_user, new_options). Exactly one of doctor/question is set."""
    options = state.get("doctor_options") or []
    if request.doctor_option and 1 <= request.doctor_option <= len(options):
        return await tools.get_doctor(options[request.doctor_option - 1]["id"]), None, None
    name = (request.doctor_name or "").replace("Dr.", "").strip()  # "Dr." alone is not a name
    if name:
        matches = (await tools.search_doctors(name=name)).doctors
        if len(matches) == 1:
            return matches[0], None, None
        if not matches:
            return None, f"I couldn't find a doctor called {name}.", None
        new_options = [_as_option(d) for d in matches]
        question = (
            f"I found several doctors with that name:\n{_options_text(new_options)}\n"
            "Which one do you mean?"
        )
        return None, question, new_options
    if doctor_id := state.get("booking_doctor_id"):
        return await tools.get_doctor(doctor_id), None, None
    return (
        None,
        "Which doctor would you like to book with? "
        "If you tell me your symptoms, I can suggest one.",
        None,
    )


def make_booking_node(deps: AgentDeps) -> Node:
    async def booking_node(state: AgentState) -> Command[str]:
        # No static outgoing edge: every result says where to go next. A proposal goes to
        # `confirm`; anything else (a question, a refusal) to `output_guard`.
        try:
            result = await plan_booking(state)
        except (LLMError, ToolError) as exc:
            log.warning("node_failed", node="booking", error=str(exc))
            result = {"draft": APOLOGY, "draft_kind": "info"}
        if isinstance(result, Command):
            return result
        return Command(goto="output_guard", update=result)

    async def plan_booking(state: AgentState) -> dict[str, Any] | Command[str]:
        today = deps.clock().astimezone(deps.tz).date()
        prompt = BOOKING_SYSTEM_PROMPT.format(
            today=today.isoformat(),
            today_weekday=f"{today:%A}",
            timezone=deps.tz.key,
            options=_options_text(state.get("doctor_options") or []),
            current_doctor=state.get("booking_doctor_id") or "none",
        )
        request = await deps.llm.ainvoke(BookingRequest, prompt, recent_messages(state))

        doctor, question, new_options = await _resolve_doctor(deps.tools, request, state)
        if doctor is None:
            update: dict[str, Any] = {"draft": question, "draft_kind": "booking"}
            if new_options is not None:
                update["doctor_options"] = new_options
            return update
        remember: dict[str, Any] = {"booking_doctor_id": doctor.id, "draft_kind": "booking"}

        if not request.date:
            return {**remember, "draft": f"Which day would you like to see {doctor.name}?"}
        try:
            day = date.fromisoformat(request.date)
        except ValueError:
            return {**remember, "draft": "Sorry, which day did you mean?"}
        if day < today:
            return {**remember, "draft": "That date is in the past. Which upcoming day suits you?"}

        note = ""
        slot: datetime | None = None
        if request.exact_time:
            try:
                wanted = datetime.combine(day, time.fromisoformat(request.exact_time), deps.tz)
            except ValueError:
                wanted = None
            if wanted is not None:
                check = await deps.tools.check_slot(doctor.id, wanted)
                if check.ok:
                    slot = wanted.astimezone(UTC)
                else:
                    note = error_text(check.error, doctor.name, day, check.detail) + " "
        if slot is None:
            found = await deps.tools.check_availability(
                doctor.id, day, days=SEARCH_DAYS, time_of_day=request.time_of_day, limit=1
            )
            slot = found.slots[0] if found.slots else None
            if slot is not None and slot.astimezone(deps.tz).date() != day and not note:
                note = _why_not_that_day(
                    doctor.name, day, request.time_of_day, found.works_on_from_day, found.holiday
                )
        if slot is None:
            text = (
                f"I couldn't find a free slot with {doctor.name} in the next {SEARCH_DAYS} days. "
                "Would another doctor or time of day work?"
            )
            return {**remember, "draft": text}

        proposal = Proposal(
            doctor_id=doctor.id,
            doctor_name=doctor.name,
            start_utc=slot.isoformat(),
            start_local=local_label(slot, deps),
        )
        return Command(
            goto="confirm",
            update={"booking_doctor_id": doctor.id, "proposal": proposal, "draft": note},
        )

    return booking_node


def confirm_node(state: AgentState) -> Command[str]:
    proposal = state.get("proposal")
    if not proposal:
        update = {"draft": "There's nothing to confirm.", "draft_kind": "booking"}
        return Command(goto="output_guard", update=update)
    note = state.get("draft") or ""
    question = f"{note}Shall I book {proposal['start_local']} with {proposal['doctor_name']}?"
    answer = interrupt(
        {
            "type": "confirm_booking",
            "doctor": proposal["doctor_name"],
            "start": proposal["start_local"],
            "question": question.strip(),
        }
    )
    if is_yes(answer):
        return Command(goto="book_appointment")
    return Command(
        goto="output_guard",
        update={
            "proposal": None,
            "draft": "No problem. Which other day or time would suit you?",
            "draft_kind": "booking",
        },
    )


def make_book_appointment_node(deps: AgentDeps) -> ConfigNode:
    async def book_appointment_node(state: AgentState, config: RunnableConfig) -> Command[str]:
        proposal = state.get("proposal")
        done: dict[str, Any] = {"proposal": None, "draft_kind": "booking"}
        if not proposal:
            return Command(goto="output_guard", update={**done, "draft": "Nothing to book."})
        # The patient comes from the authenticated session/config, never from the conversation.
        patient_id = (config.get("configurable") or {}).get("patient_id")
        if patient_id is None:
            text = "I need to know who the appointment is for. Please log in first."
            return Command(goto="output_guard", update={**done, "draft": text})

        start = datetime.fromisoformat(proposal["start_utc"])
        try:
            result = await deps.tools.book_appointment(
                int(patient_id), proposal["doctor_id"], start
            )
            if result.ok and result.appointment_id is not None:
                text = (
                    f"Booked: {proposal['doctor_name']}, {proposal['start_local']} "
                    f"({deps.tz.key}). Confirmation #A-{result.appointment_id:04d}."
                )
                if result.calendar_event_id:
                    text += " It's in the clinic's calendar."
                return Command(
                    goto="output_guard", update={**done, "booking_doctor_id": None, "draft": text}
                )
            # Not booked (time passed, or someone was faster): offer the next slot after it.
            found = await deps.tools.check_availability(
                proposal["doctor_id"],
                start.astimezone(deps.tz).date(),
                days=SEARCH_DAYS,
                after=start,
                limit=1,
            )
        except ToolError as exc:
            log.warning("node_failed", node="book_appointment", error=str(exc))
            return Command(goto="output_guard", update={**done, "draft": APOLOGY})

        message = error_text(
            result.error, proposal["doctor_name"], start.astimezone(deps.tz).date(), result.detail
        )
        if not found.slots:
            text = f"{message} I couldn't find another free slot soon. Would another doctor work?"
            return Command(goto="output_guard", update={**done, "draft": text})
        alternative = found.slots[0]
        new_proposal = Proposal(
            doctor_id=proposal["doctor_id"],
            doctor_name=proposal["doctor_name"],
            start_utc=alternative.isoformat(),
            start_local=local_label(alternative, deps),
        )
        # Offer it through the same confirmation step (a fresh interrupt).
        return Command(goto="confirm", update={"proposal": new_proposal, "draft": f"{message} "})

    return book_appointment_node
