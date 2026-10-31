"""MedAgent clinic MCP server: scheduling tools for any MCP client (our graph, MCP Inspector,
Claude Desktop).

    uv run python -m medagent.mcp_server                       # stdio (what the graph uses)
    uv run mcp dev src/medagent/mcp_server/server.py           # open in MCP Inspector

Trust boundary: stdio only, spawned by a trusted local process. `book_appointment` and
`cancel_appointment` take a `patient_id` that the *caller* must have authenticated; exposing this
server over HTTP requires authentication first (Phase 5/8). Never print to stdout here: stdout
is the JSON-RPC channel. Logs go to stderr.
"""

import logging
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from medagent.tools.clinic import ClinicService
from medagent.tools.models import (
    AppointmentList,
    Availability,
    BookingResult,
    CancelResult,
    DoctorList,
    NearbyClinics,
    SlotCheck,
    TimeOfDay,
)

INSTRUCTIONS = (
    "Scheduling tools for the MedAgent demo clinic (synthetic doctors and patients). Times are "
    "ISO 8601 with timezone; the clinic's working hours are in Europe/Berlin. find_nearby_clinics "
    "returns real places from OpenStreetMap that cannot be booked here."
)


@lru_cache
def default_service() -> ClinicService:
    from medagent.core.config import get_settings
    from medagent.db.session import get_sessionmaker
    from medagent.integrations.calendar import calendar_from_settings
    from medagent.integrations.osm import OSMClient

    settings = get_settings()
    return ClinicService(
        session_factory=get_sessionmaker(),
        clock=lambda: datetime.now(UTC),
        tz=ZoneInfo(settings.clinic_timezone),
        slot_minutes=settings.slot_minutes,
        calendar=calendar_from_settings(settings),
        osm=OSMClient(get_sessionmaker(), overpass_url=settings.overpass_url),
        holiday_language=settings.holiday_language,
    )


def create_server(service: Callable[[], ClinicService] = default_service) -> FastMCP:
    server = FastMCP("medagent-clinic", instructions=INSTRUCTIONS, log_level="WARNING")

    @server.tool()
    def search_doctors(
        specialty: str | None = None,
        city: str | None = None,
        language: str | None = None,
        name: str | None = None,
        limit: int = 5,
    ) -> DoctorList:
        """Find bookable doctors by specialty (e.g. "Cardiologist"), city, spoken language, or
        name. Filters are combined; give `name` alone to look a doctor up by name."""
        return service().search_doctors(specialty, city, language, name, limit)

    @server.tool()
    def get_doctor(doctor_id: int) -> DoctorList:
        """Look up one doctor by id. Returns an empty list if there is no such doctor."""
        doctor = service().get_doctor(doctor_id)
        return DoctorList(doctors=[doctor] if doctor else [])

    @server.tool()
    def check_availability(
        doctor_id: int,
        from_day: date,
        days: int = 1,
        time_of_day: TimeOfDay | None = None,
        after: datetime | None = None,
        limit: int = 5,
    ) -> Availability:
        """Free appointment slots for a doctor, starting on `from_day` (YYYY-MM-DD) and looking
        `days` days ahead. Optionally only morning/afternoon/evening, or only after a time.
        Practices are closed on the public holidays of their city (`holiday` names the one on
        `from_day`, if any) and on days without working hours (`works_on_from_day`)."""
        return service().check_availability(doctor_id, from_day, days, time_of_day, after, limit)

    @server.tool()
    def check_slot(doctor_id: int, start: datetime) -> SlotCheck:
        """Check whether one exact start time can be booked, and if not, why."""
        return service().check_slot(doctor_id, start)

    @server.tool()
    def book_appointment(patient_id: int, doctor_id: int, start: datetime) -> BookingResult:
        """Book a slot after the user has confirmed it. Re-validates the slot; if someone else
        booked it first, returns error "already_booked". `patient_id` must come from an
        authenticated session, never from conversation text."""
        return service().book_appointment(patient_id, doctor_id, start)

    @server.tool()
    def list_appointments(patient_id: int, upcoming_only: bool = True) -> AppointmentList:
        """A patient's booked appointments (upcoming only by default)."""
        return service().list_appointments(patient_id, upcoming_only)

    @server.tool()
    def cancel_appointment(patient_id: int, appointment_id: int) -> CancelResult:
        """Cancel one of the patient's own future appointments, after the user has confirmed.
        Other patients' appointments are reported as not_found."""
        return service().cancel_appointment(patient_id, appointment_id)

    @server.tool()
    def find_nearby_clinics(city: str) -> NearbyClinics:
        """Real clinics, practices and hospitals near a city from OpenStreetMap (cached for 24h).
        NOT bookable here. Always show the attribution with the results."""
        return service().find_nearby_clinics(city)

    return server


mcp = create_server()


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)  # stdout is the protocol
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
