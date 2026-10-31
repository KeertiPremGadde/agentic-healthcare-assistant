"""The graph against real Postgres: doctor search, HITL booking, conflicts, restart-and-resume."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from medagent.agents.checkpointer import postgres_checkpointer
from medagent.agents.deps import AgentDeps
from medagent.agents.graph import AgentGraph, build_graph
from medagent.agents.nodes import booking as booking_module
from medagent.agents.runner import run_turn, turn_config
from medagent.agents.schemas import BookingRequest, DoctorQuery, Route, RouteDecision
from medagent.db.models import Appointment, Doctor, Patient
from medagent.db.seed import seed
from medagent.rag.answer import AnswerPayload
from medagent.schemas.specialty import Specialty
from tests.fakes import FakeAnswerLLM, FakeRetriever, FakeStructuredLLM

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


def _deps(engine: Engine, llm: FakeStructuredLLM) -> AgentDeps:
    return AgentDeps(
        session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        llm=llm,
        answer_llm=FakeAnswerLLM(
            AnswerPayload(answer="x", used_sources=[], context_sufficient=False)
        ),
        retriever=FakeRetriever(),
        clock=lambda: NOW,
        tz=BERLIN,
        slot_minutes=30,
        public_only=True,
        rag_min_score=0.7,
    )


@pytest.fixture
def llm() -> FakeStructuredLLM:
    return FakeStructuredLLM()


@pytest.fixture
def graph(engine: Engine, llm: FakeStructuredLLM, patient_id: int) -> AgentGraph:
    return build_graph(_deps(engine, llm), InMemorySaver())


def _thread() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def _appointments(session: Session) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(Appointment)) or 0


def _find_cardiologist(graph: AgentGraph, llm: FakeStructuredLLM, thread: str, pid: int) -> str:
    llm.push(
        RouteDecision(route=Route.FIND_DOCTOR, is_emergency=False),
        DoctorQuery(specialty=Specialty.CARDIOLOGIST),
    )
    result = run_turn(graph, thread, pid, message="I get palpitations when I climb stairs")
    assert result.reply is not None
    return result.reply


def _ask_to_book(
    graph: AgentGraph, llm: FakeStructuredLLM, thread: str, pid: int, request: BookingRequest
):
    llm.push(RouteDecision(route=Route.BOOK, is_emergency=False), request)
    return run_turn(graph, thread, pid, message="book it")


def test_doctor_finder_lists_doctors_of_the_chosen_specialty(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    thread = _thread()
    reply = _find_cardiologist(graph, llm, thread, patient_id)
    assert "a Cardiologist is the right specialist" in reply
    assert "1. Dr. Michael Johnson" in reply
    assert "not a diagnosis" in reply
    options = graph.get_state(turn_config(thread, patient_id)).values["doctor_options"]
    assert all(o["specialty"] == "Cardiologist" for o in options)
    assert len(options) <= 5


def test_doctor_finder_relaxes_filters_it_cannot_satisfy(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    llm.push(
        RouteDecision(route=Route.FIND_DOCTOR, is_emergency=False),
        DoctorQuery(specialty=Specialty.CARDIOLOGIST, city="Atlantis", language="Klingon"),
    )
    result = run_turn(graph, _thread(), patient_id, message="cardiologist in Atlantis")
    assert result.reply is not None
    assert "couldn't find one speaking Klingon and in Atlantis" in result.reply
    assert "1. Dr." in result.reply


def test_booking_happy_path_pauses_for_confirmation_then_books(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    thread = _thread()
    _find_cardiologist(graph, llm, thread, patient_id)
    request = BookingRequest(doctor_option=1, date=TOMORROW, time_of_day="afternoon")
    paused = _ask_to_book(graph, llm, thread, patient_id, request)

    assert paused.reply is None
    assert paused.pending is not None
    assert paused.pending["type"] == "confirm_booking"
    assert (
        paused.pending["question"] == "Shall I book Tue 3 Nov 2026, 13:00 with Dr. Michael Johnson?"
    )
    assert _appointments(session) == 0  # nothing is written before the human says yes

    done = run_turn(graph, thread, patient_id, resume=True)
    assert done.pending is None
    assert done.reply is not None
    assert done.reply.startswith(
        "Booked: Dr. Michael Johnson, Tue 3 Nov 2026, 13:00 (Europe/Berlin)"
    )
    assert "Confirmation #A-" in done.reply

    appointment = session.scalars(select(Appointment)).one()
    assert appointment.patient_id == patient_id
    assert appointment.start_time == datetime(2026, 11, 3, 12, 0, tzinfo=UTC)  # 13:00 CET
    state = graph.get_state(turn_config(thread, patient_id)).values
    assert state["proposal"] is None


def test_saying_no_books_nothing_and_asks_again(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    thread = _thread()
    _find_cardiologist(graph, llm, thread, patient_id)
    _ask_to_book(graph, llm, thread, patient_id, BookingRequest(doctor_option=1, date=TOMORROW))
    result = run_turn(graph, thread, patient_id, resume={"confirmed": False})
    assert result.reply == "No problem. Which other day or time would suit you?"
    assert _appointments(session) == 0
    # the doctor is remembered, so "Thursday then" can continue the booking
    state = graph.get_state(turn_config(thread, patient_id)).values
    assert state["booking_doctor_id"] is not None
    assert state["proposal"] is None


def test_past_date_is_refused_without_a_proposal(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    thread = _thread()
    _find_cardiologist(graph, llm, thread, patient_id)
    result = _ask_to_book(
        graph, llm, thread, patient_id, BookingRequest(doctor_option=1, date="2026-10-30")
    )
    assert result.pending is None
    assert result.reply == "That date is in the past. Which upcoming day suits you?"


def test_invalid_exact_time_offers_the_nearest_valid_slot(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    thread = _thread()
    _find_cardiologist(graph, llm, thread, patient_id)
    request = BookingRequest(doctor_option=1, date=TOMORROW, exact_time="07:00")
    result = _ask_to_book(graph, llm, thread, patient_id, request)
    assert result.pending is not None
    assert result.pending["question"].startswith(
        "That time isn't one of Dr. Michael Johnson's appointment slots."
    )
    assert "Tue 3 Nov 2026, 08:00" in result.pending["question"]  # first slot that day


def test_missing_doctor_asks_which_one(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    result = _ask_to_book(graph, llm, _thread(), patient_id, BookingRequest(date=TOMORROW))
    assert result.reply is not None
    assert result.reply.startswith("Which doctor would you like to book with?")


def test_title_alone_is_not_a_doctor_name(
    graph: AgentGraph, llm: FakeStructuredLLM, patient_id: int
) -> None:
    result = _ask_to_book(
        graph, llm, _thread(), patient_id, BookingRequest(doctor_name="Dr.", date=TOMORROW)
    )
    assert result.reply is not None
    assert result.reply.startswith("Which doctor would you like to book with?")


def test_ambiguous_name_lists_matches_and_a_number_then_resolves_it(
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
    asked = _ask_to_book(
        graph, llm, thread, patient_id, BookingRequest(doctor_name="Testmann", date=TOMORROW)
    )
    assert asked.reply is not None
    assert "I found several doctors with that name" in asked.reply
    assert "1. Dr. Anna Testmann (Dermatologist)" in asked.reply
    assert "2. Dr. Bert Testmann (Dentist)" in asked.reply

    unknown = _ask_to_book(
        graph, llm, _thread(), patient_id, BookingRequest(doctor_name="Nobody", date=TOMORROW)
    )
    assert unknown.reply == "I couldn't find a doctor called Nobody."

    # The listed matches become the numbered options, so "number 2" works next. The new doctors
    # have no schedule, so no slot is found: the point here is that the choice resolved.
    chosen = _ask_to_book(
        graph, llm, thread, patient_id, BookingRequest(doctor_option=2, date=TOMORROW)
    )
    assert chosen.reply is not None
    assert "Dr. Bert Testmann" in chosen.reply


def test_no_patient_in_config_means_no_booking(
    engine: Engine, llm: FakeStructuredLLM, patient_id: int, session: Session
) -> None:
    graph = build_graph(_deps(engine, llm), InMemorySaver())
    thread = _thread()
    _find_cardiologist(graph, llm, thread, None)  # type: ignore[arg-type]
    _ask_to_book(graph, llm, thread, None, BookingRequest(doctor_option=1, date=TOMORROW))  # type: ignore[arg-type]
    result = run_turn(graph, thread, None, resume=True)
    assert result.reply == "I need to know who the appointment is for. Please log in first."
    assert _appointments(session) == 0


def test_lost_race_is_caught_by_the_unique_index_and_offers_the_next_slot(
    graph: AgentGraph,
    llm: FakeStructuredLLM,
    patient_id: int,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = _thread()
    _find_cardiologist(graph, llm, thread, patient_id)
    paused = _ask_to_book(
        graph,
        llm,
        thread,
        patient_id,
        BookingRequest(doctor_option=1, date=TOMORROW, time_of_day="afternoon"),
    )
    assert paused.pending is not None
    proposal = graph.get_state(turn_config(thread, patient_id)).values["proposal"]

    # Another patient takes the slot *after* our re-validation passes (simulated): only the
    # database's unique index can catch this.
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
    monkeypatch.setattr(booking_module, "validate_slot", lambda *a, **k: None)

    retry = run_turn(graph, thread, patient_id, resume=True)
    assert retry.pending is not None  # back at the confirmation step with a new proposal
    assert retry.pending["question"].startswith("That time is already booked.")
    assert "Tue 3 Nov 2026, 13:30" in retry.pending["question"]

    monkeypatch.undo()
    done = run_turn(graph, thread, patient_id, resume=True)
    assert done.reply is not None
    assert done.reply.startswith("Booked: Dr. Michael Johnson, Tue 3 Nov 2026, 13:30")
    assert _appointments(session) == 2


@pytest.fixture
def test_db_url(engine: Engine) -> Iterator[str]:
    yield engine.url.render_as_string(hide_password=False)


def test_memory_and_pending_confirmation_survive_a_restart(
    engine: Engine, test_db_url: str, patient_id: int, session: Session
) -> None:
    thread = _thread()
    llm = FakeStructuredLLM()

    # Process 1: find a doctor, ask to book, get paused at the confirmation, then "crash".
    with postgres_checkpointer(test_db_url) as saver:
        graph = build_graph(_deps(engine, llm), saver)
        _find_cardiologist(graph, llm, thread, patient_id)
        paused = _ask_to_book(
            graph, llm, thread, patient_id, BookingRequest(doctor_option=1, date=TOMORROW)
        )
        assert paused.pending is not None
    del graph, saver  # nothing survives in memory

    # Process 2: brand-new connection and graph. The conversation and the pause are still there.
    with postgres_checkpointer(test_db_url) as saver2:
        graph2 = build_graph(_deps(engine, FakeStructuredLLM()), saver2)
        snapshot = graph2.get_state(turn_config(thread, patient_id))
        assert snapshot.interrupts
        assert snapshot.interrupts[0].value["doctor"] == "Dr. Michael Johnson"
        assert [m.type for m in snapshot.values["messages"]] == ["human", "ai", "human"]

        done = run_turn(graph2, thread, patient_id, resume=True)
        assert done.reply is not None
        assert done.reply.startswith("Booked: Dr. Michael Johnson")
    assert _appointments(session) == 1


def test_migrations_match_models_and_ignore_checkpointer_tables(test_db_url: str) -> None:
    """`alembic check` must see no pending changes even with LangGraph's tables present.

    Guards two things: a model change without a migration, and autogenerate proposing to drop
    the library-owned checkpointer tables (which would delete every conversation).
    """
    from alembic import command
    from alembic.config import Config

    with postgres_checkpointer(test_db_url):  # make sure the checkpointer tables exist
        pass
    command.check(Config("alembic.ini"))  # raises AutogenerateDiffsDetected on any difference
