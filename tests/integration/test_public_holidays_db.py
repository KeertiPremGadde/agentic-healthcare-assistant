"""Public holidays end to end against Postgres: the clinic tools, the booking conversation and the
MCP protocol. Two identical doctors, one in Leipzig and one in Berlin, on days where the two
cities differ: 18 November 2026 (Repentance and Prayer Day: Saxony only)."""

import uuid
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from medagent.agents.graph import build_graph
from medagent.agents.runner import run_turn
from medagent.agents.schemas import BookingRequest, Route, RouteDecision
from medagent.db.models import Appointment, Doctor, DoctorSchedule, Patient
from medagent.mcp_server.server import create_server
from medagent.tools.clinic import ClinicService, LocalClinicTools
from medagent.tools.models import Availability, SlotCheck
from tests.fakes import FakeStructuredLLM
from tests.integration.test_agent_graph_db import NOW, _deps

pytestmark = pytest.mark.integration

BERLIN = ZoneInfo("Europe/Berlin")
REPENTANCE_DAY = date(2026, 11, 18)  # Wednesday: closed in Saxony, open in Berlin
CHRISTMAS = date(2026, 12, 25)  # Friday: closed everywhere
NEXT_DAY = date(2026, 11, 19)


def make_doctor(session: Session, name: str, city: str) -> Doctor:
    doctor = Doctor(name=name, specialty="Cardiologist", city=city)
    doctor.schedules = [
        DoctorSchedule(weekday=d, start_time=time(8), end_time=time(12)) for d in range(5)
    ]
    session.add(doctor)
    session.commit()
    return doctor


def at(day: date, hour: int = 9) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=BERLIN)


@pytest.fixture
def doctors(session: Session) -> dict[str, Doctor]:
    return {
        "leipzig": make_doctor(session, "Dr. Leipzig Test", "Leipzig"),
        "berlin": make_doctor(session, "Dr. Berlin Test", "Berlin"),
        "nowhere": make_doctor(session, "Dr. Nowhere Test", "Kleinkleckersdorf"),
    }


@pytest.fixture
def patient(session: Session) -> Patient:
    person = Patient(name="holiday-test")
    session.add(person)
    session.commit()
    return person


def service_for(engine: Engine, language: str = "en_US") -> ClinicService:
    return ClinicService(
        sessionmaker(bind=engine, expire_on_commit=False),
        lambda: NOW,
        BERLIN,
        30,
        holiday_language=language,
    )


def appointments(session: Session) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(Appointment)) or 0


# ------------------------------------------------------------------ the clinic tools
def test_availability_is_empty_on_a_holiday_and_names_it(
    engine: Engine, doctors: dict[str, Doctor]
) -> None:
    service = service_for(engine)
    leipzig = service.check_availability(doctors["leipzig"].id, REPENTANCE_DAY)
    assert leipzig.slots == []
    assert leipzig.holiday == "Repentance and Prayer Day"
    assert leipzig.works_on_from_day  # she works Wednesdays: it is the holiday, not her schedule

    berlin = service.check_availability(doctors["berlin"].id, REPENTANCE_DAY)
    assert berlin.holiday is None
    assert berlin.slots[0] == at(REPENTANCE_DAY, 8).astimezone(UTC)


def test_the_next_free_slot_skips_the_holiday(engine: Engine, doctors: dict[str, Doctor]) -> None:
    service = service_for(engine)
    found = service.check_availability(doctors["leipzig"].id, REPENTANCE_DAY, days=3, limit=1)
    assert found.slots == [at(NEXT_DAY, 8).astimezone(UTC)]
    assert found.holiday == "Repentance and Prayer Day"  # still reported for the requested day


def test_check_slot_reports_the_holiday_and_its_name(
    engine: Engine, doctors: dict[str, Doctor]
) -> None:
    service = service_for(engine)
    closed = service.check_slot(doctors["leipzig"].id, at(REPENTANCE_DAY))
    assert (closed.ok, closed.error, closed.detail) == (
        False,
        "public_holiday",
        "Repentance and Prayer Day",
    )
    assert service.check_slot(doctors["berlin"].id, at(REPENTANCE_DAY)).ok
    assert service.check_slot(doctors["leipzig"].id, at(NEXT_DAY)).ok


def test_booking_on_a_holiday_is_refused_by_the_tool_itself(
    engine: Engine, doctors: dict[str, Doctor], patient: Patient, session: Session
) -> None:
    """Not only the conversation: the booking tool re-validates, so calling it directly (as the
    MCP server does) can't book a closed day either."""
    service = service_for(engine)
    refused = service.book_appointment(patient.id, doctors["leipzig"].id, at(REPENTANCE_DAY))
    assert not refused.ok
    assert (refused.error, refused.detail) == ("public_holiday", "Repentance and Prayer Day")
    assert appointments(session) == 0

    assert service.book_appointment(patient.id, doctors["berlin"].id, at(REPENTANCE_DAY)).ok
    assert service.book_appointment(patient.id, doctors["leipzig"].id, at(NEXT_DAY)).ok
    assert appointments(session) == 2


def test_national_holidays_close_every_city_including_unknown_ones(
    engine: Engine, doctors: dict[str, Doctor]
) -> None:
    service = service_for(engine)
    for doctor in doctors.values():
        check = service.check_slot(doctor.id, at(CHRISTMAS))
        assert (check.error, check.detail) == ("public_holiday", "Christmas Day"), doctor.name


def test_a_city_that_is_not_in_the_table_gets_national_holidays_only(
    engine: Engine, doctors: dict[str, Doctor]
) -> None:
    service = service_for(engine)
    assert service.check_slot(doctors["nowhere"].id, at(REPENTANCE_DAY)).ok  # regional: ignored


def test_holiday_names_can_be_german(engine: Engine, doctors: dict[str, Doctor]) -> None:
    service = service_for(engine, "de")
    check = service.check_slot(doctors["leipzig"].id, at(REPENTANCE_DAY))
    assert check.detail == "Buß- und Bettag"


def test_a_weekend_is_still_closed_by_the_schedule_not_the_calendar(
    engine: Engine, doctors: dict[str, Doctor]
) -> None:
    saturday = date(2026, 11, 21)
    check = service_for(engine).check_slot(doctors["berlin"].id, at(saturday))
    assert check.error == "not_a_working_day"  # weekends stay closed via the schedules


# ------------------------------------------------------------------ the conversation
async def book_by_name(engine: Engine, patient: Patient, name: str, request: BookingRequest) -> str:
    llm = FakeStructuredLLM({RouteDecision: [RouteDecision(route=Route.BOOK, is_emergency=False)]})
    llm.push(request)
    graph = build_graph(_deps(engine, llm, LocalClinicTools(service_for(engine))), InMemorySaver())
    result = await run_turn(graph, f"t-{uuid.uuid4().hex[:8]}", patient.id, message=f"book {name}")
    assert result.pending is not None, result.reply
    return str(result.pending["question"])


async def test_the_reply_explains_the_closure_and_offers_the_next_free_slot(
    engine: Engine, doctors: dict[str, Doctor], patient: Patient
) -> None:
    request = BookingRequest(
        doctor_name="Leipzig Test", date=REPENTANCE_DAY.isoformat(), time_of_day="morning"
    )
    question = await book_by_name(engine, patient, "Leipzig", request)
    assert question == (
        "Dr. Leipzig Test's practice is closed on Wed 18 Nov 2026 (Repentance and Prayer Day). "
        "Shall I book Thu 19 Nov 2026, 08:00 with Dr. Leipzig Test?"
    )


async def test_the_same_request_in_berlin_simply_proposes_the_day(
    engine: Engine, doctors: dict[str, Doctor], patient: Patient
) -> None:
    request = BookingRequest(
        doctor_name="Berlin Test", date=REPENTANCE_DAY.isoformat(), time_of_day="morning"
    )
    question = await book_by_name(engine, patient, "Berlin", request)
    assert question == "Shall I book Wed 18 Nov 2026, 08:00 with Dr. Berlin Test?"


async def test_an_exact_time_on_a_holiday_gets_the_same_explanation(
    engine: Engine, doctors: dict[str, Doctor], patient: Patient
) -> None:
    request = BookingRequest(
        doctor_name="Leipzig Test", date=REPENTANCE_DAY.isoformat(), exact_time="10:00"
    )
    question = await book_by_name(engine, patient, "Leipzig", request)
    assert question.startswith(
        "Dr. Leipzig Test's practice is closed on Wed 18 Nov 2026 (Repentance and Prayer Day). "
    )
    assert "Thu 19 Nov 2026, 08:00" in question


async def test_christmas_is_explained_as_a_closure_in_every_city(
    engine: Engine, doctors: dict[str, Doctor], patient: Patient
) -> None:
    request = BookingRequest(doctor_name="Berlin Test", date=CHRISTMAS.isoformat())
    question = await book_by_name(engine, patient, "Berlin", request)
    assert question.startswith(
        "Dr. Berlin Test's practice is closed on Fri 25 Dec 2026 (Christmas Day). "
    )
    assert "Mon 28 Dec 2026, 08:00" in question  # 26 Dec is a Saturday: the next working day


# ------------------------------------------------------------------ through the MCP protocol
async def test_the_mcp_tools_carry_the_holiday_to_the_client(
    engine: Engine, doctors: dict[str, Doctor]
) -> None:
    server = create_server(lambda: service_for(engine))
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        availability = await client.call_tool(
            "check_availability",
            {"doctor_id": doctors["leipzig"].id, "from_day": REPENTANCE_DAY.isoformat()},
        )
        parsed = Availability.model_validate(availability.structuredContent)
        assert parsed.slots == []
        assert parsed.holiday == "Repentance and Prayer Day"

        slot = await client.call_tool(
            "check_slot",
            {"doctor_id": doctors["leipzig"].id, "start": at(REPENTANCE_DAY).isoformat()},
        )
        check = SlotCheck.model_validate(slot.structuredContent)
        assert (check.error, check.detail) == ("public_holiday", "Repentance and Prayer Day")

        tools = {t.name: t for t in (await client.list_tools()).tools}
        description = tools["check_availability"].description or ""
        assert "public holidays" in description  # the model-facing documentation says so
