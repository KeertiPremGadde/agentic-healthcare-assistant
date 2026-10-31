"""The graph against real Postgres: doctor search, HITL booking and cancelling, the optional
calendar, conflicts, restart-and-resume, and booking through the real MCP server over stdio."""

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from medagent.agents.checkpointer import postgres_checkpointer
from medagent.agents.deps import AgentDeps
from medagent.agents.graph import AgentGraph, build_graph
from medagent.agents.runner import TurnResult, run_turn, turn_config
from medagent.agents.schemas import (
    BookingRequest,
    CancelRequest,
    DoctorQuery,
    Route,
    RouteDecision,
)
from medagent.db.models import Appointment, AppointmentStatus, Doctor, Patient
from medagent.db.seed import seed
from medagent.integrations.calendar import Calendar, NullCalendar
from medagent.rag.answer import AnswerPayload
from medagent.schemas.specialty import Specialty
from medagent.tools import clinic as clinic_module
from medagent.tools.clinic import ClinicService, ClinicTools, LocalClinicTools
from tests.fakes import FakeAnswerLLM, FakeCalendar, FakeRetriever, FakeStructuredLLM

pytestmark = pytest.mark.integration

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)  # Monday 09:00 in Berlin
TOMORROW = "2026-11-03"  # Tuesday


@pytest.fixture
def patient_id(session: Session) -> int:
    seed(session)
    patient = session.scalars(select(Patient).order_by(Patient.id)).first()
    assert patient is not None
    return patient.id


def _service(engine: Engine, calendar: Calendar | None = None) -> ClinicService:
    return ClinicService(
        session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        clock=lambda: NOW,
        tz=BERLIN,
        slot_minutes=30,
        calendar=calendar or NullCalendar(),
    )


def _deps(engine: Engine, llm: FakeStructuredLLM, tools: ClinicTools) -> AgentDeps:
    return AgentDeps(
        tools=tools,
        llm=llm,
        answer_llm=FakeAnswerLLM(
            AnswerPayload(answer="x", used_sources=[], context_sufficient=False)
        ),
        retriever=FakeRetriever(),
        session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        clock=lambda: NOW,
        tz=BERLIN,
        public_only=True,
        rag_min_score=0.7,
    )


@pytest.fixture
def llm() -> FakeStructuredLLM:
    return FakeStructuredLLM()


@pytest.fixture
def calendar() -> FakeCalendar:
    return FakeCalendar()


@pytest.fixture
def graph(
    engine: Engine, llm: FakeStructuredLLM, calendar: FakeCalendar, patient_id: int
) -> AgentGraph:
    tools = LocalClinicTools(_service(engine, calendar))
    return build_graph(_deps(engine, llm, tools), InMemorySaver())


def _thread() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def _appointments(session: Session) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(Appointment)) or 0


async def _find_cardiologist(
    graph: AgentGraph, llm: FakeStructuredLLM, thread: str, pid: int | None
) -> str:
    llm.push(
        RouteDecision(route=Route.FIND_DOCTOR, is_emergency=False),
        DoctorQuery(specialty=Specialty.CARDIOLOGIST),
    )
    result = await run_turn(graph, thread, pid, message="I get palpitations when I climb stairs")
    assert result.reply is not None
    return result.reply


async def _ask_to_book(
    graph: AgentGraph,
    llm: FakeStructuredLLM,
    thread: str,
    pid: int | None,
    request: BookingRequest,
) -> TurnResult:
    llm.push(RouteDecision(route=Route.BOOK, is_emergency=False), request)
    return await run_turn(graph, thread, pid, message="book it")


async def _book(
    graph: AgentGraph, llm: FakeStructuredLLM, thread: str, pid: int, request: BookingRequest
) -> TurnResult:
    await _find_cardiologist(graph, llm, thread, pid)
    paused = await _ask_to_book(graph, llm, thread, pid, request)
    assert paused.pending is not None, paused.reply
    return await run_turn(graph, thread, pid, resume=True)


# -- doctor search ---------------------------------------------------------------------------
async def test_doctor_finder_lists_doctors_of_the_chosen_specialty(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    thread = _thread()
    reply = await _find_cardiologist(graph, llm, thread, patient_id)
    assert "a Cardiologist is the right specialist" in reply
    assert "1. Dr. Michael Johnson" in reply
    assert "not a diagnosis" in reply
    options = (await graph.aget_state(turn_config(thread, patient_id))).values["doctor_options"]
    assert all(o["specialty"] == "Cardiologist" for o in options)
    assert len(options) <= 5


async def test_doctor_finder_relaxes_filters_it_cannot_satisfy(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    llm.push(
        RouteDecision(route=Route.FIND_DOCTOR, is_emergency=False),
        DoctorQuery(specialty=Specialty.CARDIOLOGIST, city="Atlantis", language="Klingon"),
    )
    result = await run_turn(graph, _thread(), patient_id, message="cardiologist in Atlantis")
    assert result.reply is not None
    assert "couldn't find one speaking Klingon and in Atlantis" in result.reply
    assert "1. Dr." in result.reply


# -- booking (HITL) ----------------------------------------------------------------------------
async def test_booking_happy_path_pauses_for_confirmation_then_books(
    graph: AgentGraph,
    llm: FakeStructuredLLM,
    calendar: FakeCalendar,
    patient_id: int,
    session: Session,
) -> None:
    thread = _thread()
    await _find_cardiologist(graph, llm, thread, patient_id)
    request = BookingRequest(doctor_option=1, date=TOMORROW, time_of_day="afternoon")
    paused = await _ask_to_book(graph, llm, thread, patient_id, request)

    assert paused.reply is None
    assert paused.pending is not None
    assert paused.pending["type"] == "confirm_booking"
    assert paused.pending["question"] == (
        "Shall I book Tue 3 Nov 2026, 13:00 with Dr. Michael Johnson?"
    )
    assert _appointments(session) == 0  # nothing is written before the human says yes

    done = await run_turn(graph, thread, patient_id, resume=True)
    assert done.reply is not None
    assert done.reply.startswith(
        "Booked: Dr. Michael Johnson, Tue 3 Nov 2026, 13:00 (Europe/Berlin)"
    )
    assert "It's in the clinic's calendar." in done.reply

    appointment = session.scalars(select(Appointment)).one()
    assert appointment.patient_id == patient_id
    assert appointment.start_time == datetime(2026, 11, 3, 12, 0, tzinfo=UTC)  # 13:00 CET
    assert calendar.added == [appointment.id]
    assert appointment.calendar_event_id == f"medagent{appointment.id:08d}"
    state = (await graph.aget_state(turn_config(thread, patient_id))).values
    assert state["proposal"] is None


async def test_booking_works_without_a_calendar(
    engine: Engine, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    graph = build_graph(_deps(engine, llm, LocalClinicTools(_service(engine))), InMemorySaver())
    request = BookingRequest(doctor_option=1, date=TOMORROW)
    done = await _book(graph, llm, _thread(), patient_id, request)
    assert done.reply is not None
    assert done.reply.startswith("Booked:")
    assert "calendar" not in done.reply
    assert session.scalars(select(Appointment)).one().calendar_event_id is None


async def test_calendar_failure_never_undoes_a_booking(
    engine: Engine, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    tools = LocalClinicTools(_service(engine, FakeCalendar(fail=True)))
    graph = build_graph(_deps(engine, llm, tools), InMemorySaver())
    request = BookingRequest(doctor_option=1, date=TOMORROW)
    done = await _book(graph, llm, _thread(), patient_id, request)
    assert done.reply is not None
    assert done.reply.startswith("Booked:")
    appointment = session.scalars(select(Appointment)).one()
    assert appointment.status is AppointmentStatus.BOOKED
    assert appointment.calendar_event_id is None


async def test_saying_no_books_nothing_and_asks_again(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    thread = _thread()
    await _find_cardiologist(graph, llm, thread, patient_id)
    request = BookingRequest(doctor_option=1, date=TOMORROW)
    await _ask_to_book(graph, llm, thread, patient_id, request)
    result = await run_turn(graph, thread, patient_id, resume={"confirmed": False})
    assert result.reply == "No problem. Which other day or time would suit you?"
    assert _appointments(session) == 0
    state = (await graph.aget_state(turn_config(thread, patient_id))).values
    assert state["booking_doctor_id"] is not None  # "Thursday then" can continue the booking
    assert state["proposal"] is None


async def test_past_date_is_refused_without_a_proposal(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    thread = _thread()
    await _find_cardiologist(graph, llm, thread, patient_id)
    result = await _ask_to_book(
        graph, llm, thread, patient_id, BookingRequest(doctor_option=1, date="2026-10-30")
    )
    assert result.pending is None
    assert result.reply == "That date is in the past. Which upcoming day suits you?"


async def test_invalid_exact_time_offers_the_nearest_valid_slot(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    thread = _thread()
    await _find_cardiologist(graph, llm, thread, patient_id)
    request = BookingRequest(doctor_option=1, date=TOMORROW, exact_time="07:00")
    result = await _ask_to_book(graph, llm, thread, patient_id, request)
    assert result.pending is not None
    assert result.pending["question"].startswith(
        "That time isn't one of Dr. Michael Johnson's appointment slots."
    )
    assert "Tue 3 Nov 2026, 08:00" in result.pending["question"]


async def test_missing_doctor_asks_which_one(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    result = await _ask_to_book(graph, llm, _thread(), patient_id, BookingRequest(date=TOMORROW))
    assert result.reply is not None
    assert result.reply.startswith("Which doctor would you like to book with?")


async def test_title_alone_is_not_a_doctor_name(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    request = BookingRequest(doctor_name="Dr.", date=TOMORROW)
    result = await _ask_to_book(graph, llm, _thread(), patient_id, request)
    assert result.reply is not None
    assert result.reply.startswith("Which doctor would you like to book with?")


async def test_ambiguous_name_lists_matches_and_a_number_then_resolves_it(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    session.add_all(
        [
            Doctor(name="Dr. Anna Testmann", specialty="Dermatologist"),
            Doctor(name="Dr. Bert Testmann", specialty="Dentist"),
        ]
    )
    session.commit()
    thread = _thread()
    asked = await _ask_to_book(
        graph, llm, thread, patient_id, BookingRequest(doctor_name="Testmann", date=TOMORROW)
    )
    assert asked.reply is not None
    assert "1. Dr. Anna Testmann (Dermatologist)" in asked.reply
    assert "2. Dr. Bert Testmann (Dentist)" in asked.reply
    unknown = await _ask_to_book(
        graph, llm, _thread(), patient_id, BookingRequest(doctor_name="Nobody", date=TOMORROW)
    )
    assert unknown.reply == "I couldn't find a doctor called Nobody."
    chosen = await _ask_to_book(
        graph, llm, thread, patient_id, BookingRequest(doctor_option=2, date=TOMORROW)
    )
    assert chosen.reply is not None
    assert "Dr. Bert Testmann" in chosen.reply  # no schedule, but the choice resolved


async def test_no_patient_in_config_means_no_booking(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    thread = _thread()
    await _find_cardiologist(graph, llm, thread, None)
    await _ask_to_book(graph, llm, thread, None, BookingRequest(doctor_option=1, date=TOMORROW))
    result = await run_turn(graph, thread, None, resume=True)
    assert result.reply == "I need to know who the appointment is for. Please log in first."
    assert _appointments(session) == 0


async def test_lost_race_is_caught_by_the_unique_index_and_offers_the_next_slot(
    graph: AgentGraph,
    llm: FakeStructuredLLM,
    patient_id: int,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = _thread()
    await _find_cardiologist(graph, llm, thread, patient_id)
    request = BookingRequest(doctor_option=1, date=TOMORROW, time_of_day="afternoon")
    paused = await _ask_to_book(graph, llm, thread, patient_id, request)
    assert paused.pending is not None
    proposal = (await graph.aget_state(turn_config(thread, patient_id))).values["proposal"]

    # Another patient takes the slot *after* the tool's re-validation (simulated by skipping
    # it): only the database's unique index can catch this.
    other = session.scalars(select(Patient).where(Patient.id != patient_id)).first()
    assert other is not None
    session.add(
        Appointment(
            patient_id=other.id,
            doctor_id=proposal["doctor_id"],
            start_time=datetime.fromisoformat(proposal["start_utc"]),
        )
    )
    session.commit()
    monkeypatch.setattr(clinic_module, "validate_slot", lambda *a, **k: None)

    retry = await run_turn(graph, thread, patient_id, resume=True)
    assert retry.pending is not None  # back at the confirmation step with a new proposal
    assert retry.pending["question"].startswith("That time is already booked.")
    assert "Tue 3 Nov 2026, 13:30" in retry.pending["question"]

    monkeypatch.undo()
    done = await run_turn(graph, thread, patient_id, resume=True)
    assert done.reply is not None
    assert done.reply.startswith("Booked: Dr. Michael Johnson, Tue 3 Nov 2026, 13:30")
    assert _appointments(session) == 2


# -- cancelling (HITL) -------------------------------------------------------------------------
async def _ask_to_cancel(
    graph: AgentGraph, llm: FakeStructuredLLM, thread: str, pid: int, option: int | None = None
) -> TurnResult:
    llm.push(RouteDecision(route=Route.CANCEL, is_emergency=False))
    if option is not None:
        llm.push(CancelRequest(appointment_option=option))
    return await run_turn(graph, thread, pid, message="cancel my appointment")


async def test_cancel_single_appointment_with_confirmation(
    graph: AgentGraph,
    llm: FakeStructuredLLM,
    calendar: FakeCalendar,
    patient_id: int,
    session: Session,
) -> None:
    thread = _thread()
    await _book(graph, llm, thread, patient_id, BookingRequest(doctor_option=1, date=TOMORROW))
    appointment_id = session.scalars(select(Appointment)).one().id

    paused = await _ask_to_cancel(graph, llm, thread, patient_id)  # one appointment: no LLM pick
    assert paused.pending is not None
    assert paused.pending["type"] == "confirm_cancel"
    assert "Dr. Michael Johnson" in paused.pending["question"]
    session.expire_all()
    appointment = session.get(Appointment, appointment_id)
    assert appointment is not None
    assert appointment.status is AppointmentStatus.BOOKED  # nothing changes before "yes"

    done = await run_turn(graph, thread, patient_id, resume=True)
    assert done.reply is not None
    assert done.reply.startswith("Cancelled: Dr. Michael Johnson")
    session.expire_all()
    appointment = session.get(Appointment, appointment_id)
    assert appointment is not None
    assert appointment.status is AppointmentStatus.CANCELLED
    assert calendar.removed == [appointment_id]


async def test_cancel_asks_which_one_when_there_are_several_and_no_keeps_it(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    thread = _thread()
    await _book(graph, llm, thread, patient_id, BookingRequest(doctor_option=1, date=TOMORROW))
    await _book(graph, llm, thread, patient_id, BookingRequest(doctor_option=2, date=TOMORROW))

    llm.push(RouteDecision(route=Route.CANCEL, is_emergency=False), CancelRequest())
    asked = await run_turn(graph, thread, patient_id, message="cancel an appointment")
    assert asked.reply is not None
    assert asked.reply.startswith("Which appointment would you like to cancel?")
    assert "1. Dr." in asked.reply
    assert "2. Dr." in asked.reply

    paused = await _ask_to_cancel(graph, llm, thread, patient_id, option=2)
    assert paused.pending is not None
    kept = await run_turn(graph, thread, patient_id, resume=False)
    assert kept.reply == "OK, I've kept your appointment."
    session.expire_all()
    assert {a.status for a in session.scalars(select(Appointment))} == {AppointmentStatus.BOOKED}


async def test_cancel_with_nothing_booked(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    result = await _ask_to_cancel(graph, llm, _thread(), patient_id)
    assert result.reply == "You have no upcoming appointments to cancel."


# -- memory across restarts --------------------------------------------------------------------
async def test_memory_and_pending_confirmation_survive_a_restart(
    engine: Engine, patient_id: int, session: Session
) -> None:
    url = engine.url.render_as_string(hide_password=False)
    thread = _thread()
    llm = FakeStructuredLLM()
    tools = LocalClinicTools(_service(engine))

    # Process 1: find a doctor, ask to book, get paused at the confirmation, then "crash".
    async with postgres_checkpointer(url) as saver:
        graph = build_graph(_deps(engine, llm, tools), saver)
        await _find_cardiologist(graph, llm, thread, patient_id)
        paused = await _ask_to_book(
            graph, llm, thread, patient_id, BookingRequest(doctor_option=1, date=TOMORROW)
        )
        assert paused.pending is not None
    del graph, saver

    # Process 2: brand-new connection and graph. The conversation and the pause are still there.
    async with postgres_checkpointer(url) as saver2:
        graph2 = build_graph(_deps(engine, FakeStructuredLLM(), tools), saver2)
        snapshot = await graph2.aget_state(turn_config(thread, patient_id))
        assert snapshot.interrupts
        assert snapshot.interrupts[0].value["doctor"] == "Dr. Michael Johnson"
        assert [m.type for m in snapshot.values["messages"]] == ["human", "ai", "human"]
        done = await run_turn(graph2, thread, patient_id, resume=True)
        assert done.reply is not None
        assert done.reply.startswith("Booked: Dr. Michael Johnson")
    assert _appointments(session) == 1


async def test_migrations_match_models_and_ignore_checkpointer_tables(engine: Engine) -> None:
    """`alembic check` must see no pending changes even with LangGraph's tables present.

    Guards two things: a model change without a migration, and autogenerate proposing to drop
    the library-owned checkpointer tables (which would delete every conversation).
    """
    from alembic import command
    from alembic.config import Config

    async with postgres_checkpointer(engine.url.render_as_string(hide_password=False)):
        pass  # make sure the checkpointer tables exist
    command.check(Config("alembic.ini"))  # raises AutogenerateDiffsDetected on any difference


# -- through the real MCP server ---------------------------------------------------------------
async def test_graph_books_and_cancels_through_the_mcp_server_over_stdio(
    engine: Engine, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    """The same flow, but every tool call crosses the MCP boundary: a separate server process
    over stdio, pointed at the test database through its environment."""
    from medagent.core.config import get_settings
    from medagent.tools.mcp_client import MCPClinicTools

    async with MCPClinicTools(get_settings()) as tools:
        graph = build_graph(_deps(engine, llm, tools), InMemorySaver())
        thread = _thread()
        await _find_cardiologist(graph, llm, thread, patient_id)
        # The server's clock is real time, so book a date safely in the future.
        future = BookingRequest(doctor_option=1, date="2027-03-02", time_of_day="morning")
        paused = await _ask_to_book(graph, llm, thread, patient_id, future)
        assert paused.pending is not None, paused.reply
        assert "Tue 2 Mar 2027" in paused.pending["question"]

        booked = await run_turn(graph, thread, patient_id, resume=True)
        assert booked.reply is not None
        assert booked.reply.startswith("Booked: Dr. Michael Johnson, Tue 2 Mar 2027")

        cancel_paused = await _ask_to_cancel(graph, llm, thread, patient_id)
        assert cancel_paused.pending is not None
        cancelled = await run_turn(graph, thread, patient_id, resume=True)
        assert cancelled.reply is not None
        assert cancelled.reply.startswith("Cancelled:")
    session.expire_all()
    assert session.scalars(select(Appointment)).one().status is AppointmentStatus.CANCELLED
