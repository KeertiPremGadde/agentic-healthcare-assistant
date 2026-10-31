"""Booking with human-in-the-loop confirmation.

    booking ──> confirm ──yes──> book_appointment
                   └──no──> (ask for another day/time)

`confirm` calls `interrupt()`: the graph stops, the state is checkpointed, and the caller shows
the proposal. On resume LangGraph re-runs the interrupted node *from the start*, so `confirm`
has no side effects at all; the database write lives in the next node and re-validates the slot.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt
from sqlalchemy.orm import Session

from medagent.agents.deps import AgentDeps
from medagent.agents.llm import LLMError
from medagent.agents.nodes.common import APOLOGY, ConfigNode, Node, recent_messages
from medagent.agents.prompts.booking import BOOKING_SYSTEM_PROMPT
from medagent.agents.schemas import BookingRequest
from medagent.agents.state import AgentState, DoctorOption, Proposal
from medagent.db import repository
from medagent.db.models import Doctor
from medagent.services.availability import WorkingWindow, free_slots
from medagent.services.validation import BookingError, validate_slot

log = structlog.get_logger("medagent.agents")
SEARCH_DAYS = 14
TimeOfDay = Literal["morning", "afternoon", "evening"] | None

ERROR_TEXT = {
    BookingError.IN_THE_PAST: "That time has already passed.",
    BookingError.NOT_A_WORKING_DAY: "{doctor} doesn't work on that day.",
    BookingError.OUTSIDE_WORKING_HOURS: "That time isn't one of {doctor}'s appointment slots.",
    BookingError.ALREADY_BOOKED: "That time is already booked.",
}
YES = frozenset({"yes", "y", "ja", "j", "confirm"})  # explicit tokens only, not free-text parsing


def local_label(start_utc: datetime, deps: AgentDeps) -> str:
    local = start_utc.astimezone(deps.tz)
    return f"{local:%a} {local.day} {local:%b %Y}, {local:%H:%M}"


def _matches_time_of_day(start_utc: datetime, deps: AgentDeps, tod: TimeOfDay) -> bool:
    hour = start_utc.astimezone(deps.tz).hour
    if tod == "morning":
        return hour < 12
    if tod == "afternoon":
        return 12 <= hour < 17
    if tod == "evening":
        return hour >= 17
    return True


def first_free_slot(
    session: Session,
    deps: AgentDeps,
    doctor_id: int,
    windows: list[WorkingWindow],
    from_day: date,
    tod: TimeOfDay = None,
    after: datetime | None = None,
) -> datetime | None:
    """First free slot from `from_day` on, optionally only later than `after` (so a lost slot
    is replaced by the next one, not by the first slot of the morning)."""
    earliest = max(deps.clock(), after) if after else deps.clock()
    for offset in range(SEARCH_DAYS):
        day = from_day + timedelta(days=offset)
        booked = repository.get_booked_starts(session, doctor_id, day, deps.tz)
        for slot in free_slots(day, windows, booked, earliest, deps.tz, deps.slot_minutes):
            if _matches_time_of_day(slot, deps, tod):
                return slot
    return None


def _options_text(options: list[DoctorOption]) -> str:
    return "\n".join(f"{i}. {o['name']} ({o['specialty']})" for i, o in enumerate(options, 1)) or (
        "None."
    )


def _resolve_doctor(
    session: Session, request: BookingRequest, state: AgentState
) -> tuple[Doctor | None, str | None, list[DoctorOption] | None]:
    """Return (doctor, question_for_user, new_options). Exactly one of doctor/question is set."""
    options = state.get("doctor_options") or []
    if request.doctor_option and 1 <= request.doctor_option <= len(options):
        return repository.get_doctor(session, options[request.doctor_option - 1]["id"]), None, None
    name = (request.doctor_name or "").replace("Dr.", "").strip()  # "Dr." alone is not a name
    if name:
        matches = repository.find_doctors_by_name(session, name)
        if len(matches) == 1:
            return matches[0], None, None
        if not matches:
            return None, f"I couldn't find a doctor called {name}.", None
        new_options = [
            DoctorOption(
                id=d.id, name=d.name, specialty=d.specialty, city=d.city, languages=d.languages
            )
            for d in matches
        ]
        return (
            None,
            "I found several doctors with that name:\n"
            + _options_text(new_options)
            + ("\nWhich one do you mean?"),
            new_options,
        )
    if doctor_id := state.get("booking_doctor_id"):
        return repository.get_doctor(session, doctor_id), None, None
    return (
        None,
        "Which doctor would you like to book with? "
        "If you tell me your symptoms, I can suggest one.",
        None,
    )


def make_booking_node(deps: AgentDeps) -> Node:
    def booking_node(state: AgentState) -> Command[str]:
        # This node has no static outgoing edge, so every result must say where to go next:
        # a proposal goes to `confirm`, anything else (a question, a refusal) to `output_guard`.
        result = plan_booking(state)
        if isinstance(result, Command):
            return result
        return Command(goto="output_guard", update=result)

    def plan_booking(state: AgentState) -> dict[str, Any] | Command[str]:
        today = deps.clock().astimezone(deps.tz).date()
        prompt = BOOKING_SYSTEM_PROMPT.format(
            today=today.isoformat(),
            today_weekday=f"{today:%A}",
            timezone=deps.tz.key,
            options=_options_text(state.get("doctor_options") or []),
            current_doctor=state.get("booking_doctor_id") or "none",
        )
        try:
            request = deps.llm.invoke(BookingRequest, prompt, recent_messages(state))
        except LLMError as exc:
            log.warning("node_failed", node="booking", error=str(exc))
            return {"draft": APOLOGY, "draft_kind": "info"}

        with deps.session_factory() as session:
            doctor, question, new_options = _resolve_doctor(session, request, state)
            if doctor is None:
                update: dict[str, Any] = {"draft": question, "draft_kind": "booking"}
                if new_options is not None:
                    update["doctor_options"] = new_options
                return update
            remember: dict[str, Any] = {"booking_doctor_id": doctor.id}

            if not request.date:
                return {
                    **remember,
                    "draft": f"Which day would you like to see {doctor.name}?",
                    "draft_kind": "booking",
                }
            try:
                day = date.fromisoformat(request.date)
            except ValueError:
                return {
                    **remember,
                    "draft": "Sorry, which day did you mean?",
                    "draft_kind": "booking",
                }
            if day < today:
                return {
                    **remember,
                    "draft": "That date is in the past. Which upcoming day suits you?",
                    "draft_kind": "booking",
                }

            windows = repository.get_working_windows(session, doctor.id)
            note = ""
            slot: datetime | None = None
            if request.exact_time:
                try:
                    wanted = datetime.combine(day, time.fromisoformat(request.exact_time), deps.tz)
                except ValueError:
                    wanted = None
                if wanted is not None:
                    booked = repository.get_booked_starts(session, doctor.id, day, deps.tz)
                    error = validate_slot(
                        wanted, windows, booked, deps.clock(), deps.tz, deps.slot_minutes
                    )
                    if error is None:
                        slot = wanted.astimezone(UTC)
                    else:
                        note = ERROR_TEXT[error].format(doctor=doctor.name) + " "
            if slot is None:
                slot = first_free_slot(session, deps, doctor.id, windows, day, request.time_of_day)
                if slot is not None and slot.astimezone(deps.tz).date() != day and not note:
                    when = f"{request.time_of_day} " if request.time_of_day else ""
                    note = f"{doctor.name} has no free {when}slot on that day. "
            if slot is None:
                return {
                    **remember,
                    "draft": (
                        f"I couldn't find a free slot with {doctor.name} "
                        f"in the next {SEARCH_DAYS} days. "
                        "Would another doctor or time of day work?"
                    ),
                    "draft_kind": "booking",
                }

            proposal = Proposal(
                doctor_id=doctor.id,
                doctor_name=doctor.name,
                start_utc=slot.isoformat(),
                start_local=local_label(slot, deps),
            )
        return Command(goto="confirm", update={**remember, "proposal": proposal, "draft": note})

    return booking_node


def _is_yes(answer: object) -> bool:
    """The UI sends a structured answer (bool or {"confirmed": bool}); the CLI may send y/n."""
    if isinstance(answer, bool):
        return answer
    if isinstance(answer, dict):
        return answer.get("confirmed") is True
    if isinstance(answer, str):
        return answer.strip().lower() in YES
    return False


def confirm_node(state: AgentState) -> Command[str]:
    proposal = state.get("proposal")
    if not proposal:
        return Command(
            goto="output_guard",
            update={"draft": "There's nothing to confirm.", "draft_kind": "booking"},
        )
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
    if _is_yes(answer):
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
    def book_appointment_node(state: AgentState, config: RunnableConfig) -> Command[str]:
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
        day = start.astimezone(deps.tz).date()
        with deps.session_factory() as session:
            windows = repository.get_working_windows(session, proposal["doctor_id"])
            booked = repository.get_booked_starts(session, proposal["doctor_id"], day, deps.tz)
            # Re-check: time has passed since the proposal (the user may confirm much later).
            error = validate_slot(start, windows, booked, deps.clock(), deps.tz, deps.slot_minutes)
            if error is None:
                try:
                    appointment = repository.create_appointment(
                        session, int(patient_id), proposal["doctor_id"], start
                    )
                except repository.SlotTakenError:
                    error = BookingError.ALREADY_BOOKED  # lost a race: the unique index decided
                else:
                    text = (
                        f"Booked: {proposal['doctor_name']}, {proposal['start_local']} "
                        f"({deps.tz.key}). Confirmation #A-{appointment.id:04d}."
                    )
                    return Command(
                        goto="output_guard",
                        update={**done, "booking_doctor_id": None, "draft": text},
                    )
            alternative = first_free_slot(
                session, deps, proposal["doctor_id"], windows, day, after=start
            )
        message = ERROR_TEXT[error].format(doctor=proposal["doctor_name"])
        if alternative is None:
            text = f"{message} I couldn't find another free slot soon. Would another doctor work?"
            return Command(goto="output_guard", update={**done, "draft": text})
        # Offer the next free slot through the same confirmation step (a fresh interrupt).
        new_proposal = Proposal(
            doctor_id=proposal["doctor_id"],
            doctor_name=proposal["doctor_name"],
            start_utc=alternative.isoformat(),
            start_local=local_label(alternative, deps),
        )
        return Command(goto="confirm", update={"proposal": new_proposal, "draft": f"{message} "})

    return book_appointment_node
