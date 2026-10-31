"""ClinicService rules against Postgres, and the same tools through the MCP protocol (in memory)."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from medagent.db.models import Patient
from medagent.db.seed import seed
from medagent.mcp_server.server import create_server
from medagent.tools.clinic import ClinicService
from medagent.tools.models import Availability, BookingResult, DoctorList
from tests.fakes import FakeCalendar

pytestmark = pytest.mark.integration

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
TUESDAY_13 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)  # 13:00 Berlin


@pytest.fixture
def service(engine: Engine, session: Session) -> ClinicService:
    seed(session)
    return ClinicService(
        sessionmaker(bind=engine, expire_on_commit=False), lambda: NOW, BERLIN, 30, FakeCalendar()
    )


@pytest.fixture
def patients(session: Session) -> tuple[int, int]:
    first, second = session.scalars(select(Patient.id).order_by(Patient.id).limit(2)).all()
    return first, second


def test_search_and_availability(service: ClinicService) -> None:
    cardiologists = service.search_doctors(specialty="Cardiologist", limit=2).doctors
    assert [d.name for d in cardiologists] == ["Dr. Michael Johnson", "Dr. Sarah Wilson"]
    by_name = service.search_doctors(name="Michael Johnson").doctors
    assert [d.id for d in by_name] == [cardiologists[0].id]

    slots = service.check_availability(
        cardiologists[0].id, date(2026, 11, 3), time_of_day="afternoon", limit=3
    ).slots
    assert slots[0] == TUESDAY_13
    assert all(12 <= s.astimezone(BERLIN).hour < 17 for s in slots)
    assert service.check_slot(cardiologists[0].id, TUESDAY_13).ok
    assert service.check_slot(cardiologists[0].id, NOW).error == "in_the_past"


def test_book_list_and_cancel_rules(service: ClinicService, patients: tuple[int, int]) -> None:
    me, someone_else = patients
    doctor_id = service.search_doctors(specialty="Cardiologist", limit=1).doctors[0].id

    booked = service.book_appointment(me, doctor_id, TUESDAY_13)
    assert booked.ok
    assert booked.calendar_event_id == f"medagent{booked.appointment_id:08d}"
    assert service.book_appointment(someone_else, doctor_id, TUESDAY_13).error == "already_booked"
    assert service.book_appointment(me, 999_999, TUESDAY_13).error == "unknown_doctor"

    mine = service.list_appointments(me).appointments
    assert [a.id for a in mine] == [booked.appointment_id]
    assert service.list_appointments(someone_else).appointments == []

    assert booked.appointment_id is not None
    # Someone else can't cancel it, and isn't told it exists.
    assert service.cancel_appointment(someone_else, booked.appointment_id).error == "not_found"
    assert service.cancel_appointment(me, booked.appointment_id).ok
    assert service.cancel_appointment(me, booked.appointment_id).error == "not_cancellable"
    assert service.list_appointments(me).appointments == []
    # The slot is free again (partial unique index).
    assert service.book_appointment(someone_else, doctor_id, TUESDAY_13).ok


async def test_mcp_tools_return_the_same_typed_results(
    service: ClinicService, patients: tuple[int, int]
) -> None:
    server = create_server(lambda: service)
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {
            "search_doctors",
            "get_doctor",
            "check_availability",
            "check_slot",
            "book_appointment",
            "list_appointments",
            "cancel_appointment",
            "find_nearby_clinics",
        }
        assert all(t.outputSchema for t in tools.values())  # typed outputs for every tool

        found = await client.call_tool("search_doctors", {"specialty": "Cardiologist", "limit": 1})
        doctor = DoctorList.model_validate(found.structuredContent).doctors[0]
        slots = await client.call_tool(
            "check_availability",
            {"doctor_id": doctor.id, "from_day": "2026-11-03", "time_of_day": "afternoon"},
        )
        first = Availability.model_validate(slots.structuredContent).slots[0]
        assert first == TUESDAY_13

        result = await client.call_tool(
            "book_appointment",
            {"patient_id": patients[0], "doctor_id": doctor.id, "start": first.isoformat()},
        )
        assert BookingResult.model_validate(result.structuredContent).ok

        bad = await client.call_tool("book_appointment", {"patient_id": "x", "doctor_id": 1})
        assert bad.isError  # schema validation happens at the MCP boundary
