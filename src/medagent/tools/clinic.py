"""Clinic operations exposed as tools.

`ClinicService` holds the logic once (sync: database, domain services, calendar, OpenStreetMap).
Two `ClinicTools` implementations give the graph the same async interface:
- `LocalClinicTools`: calls the service in-process (unit tests, `TOOLS_TRANSPORT=local`);
- `MCPClinicTools` (tools/mcp_client.py): calls the MCP server, which wraps the same service.
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta
from typing import Protocol, TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from medagent.db import repository
from medagent.db.models import AppointmentStatus, Doctor
from medagent.integrations.calendar import Calendar, CalendarEvent, NullCalendar
from medagent.integrations.osm import OSMClient
from medagent.services.availability import free_slots
from medagent.services.validation import validate_slot
from medagent.tools.models import (
    AppointmentInfo,
    AppointmentList,
    Availability,
    BookingResult,
    CancelResult,
    DoctorInfo,
    DoctorList,
    NearbyClinics,
    SlotCheck,
    TimeOfDay,
)

log = logging.getLogger(__name__)


class ToolError(Exception):
    """A tool call failed (database, network, MCP). Message never contains user text."""


R = TypeVar("R")
SessionFactory = Callable[[], AbstractContextManager[Session]]


def _doctor_info(d: Doctor) -> DoctorInfo:
    return DoctorInfo(
        id=d.id, name=d.name, specialty=d.specialty, city=d.city, languages=d.languages
    )


class ClinicService:
    def __init__(
        self,
        session_factory: SessionFactory,
        clock: Callable[[], datetime],
        tz: ZoneInfo,
        slot_minutes: int,
        calendar: Calendar | None = None,
        osm: OSMClient | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.tz = tz
        self.slot_minutes = slot_minutes
        self.calendar: Calendar = calendar or NullCalendar()
        self.osm = osm or OSMClient(session_factory)

    def _in_time_of_day(self, slot: datetime, tod: TimeOfDay | None) -> bool:
        hour = slot.astimezone(self.tz).hour
        return {
            None: True,
            "morning": hour < 12,
            "afternoon": 12 <= hour < 17,
            "evening": hour >= 17,
        }[tod]

    # -- doctors -------------------------------------------------------------------------
    def get_doctor(self, doctor_id: int) -> DoctorInfo | None:
        with self.session_factory() as session:
            doctor = repository.get_doctor(session, doctor_id)
            return _doctor_info(doctor) if doctor else None

    def search_doctors(
        self,
        specialty: str | None = None,
        city: str | None = None,
        language: str | None = None,
        name: str | None = None,
        limit: int = 5,
    ) -> DoctorList:
        with self.session_factory() as session:
            if name:
                doctors = repository.find_doctors_by_name(session, name, limit=limit)
            else:
                doctors = repository.get_doctors(session, specialty, city, language)[:limit]
            return DoctorList(doctors=[_doctor_info(d) for d in doctors])

    # -- availability --------------------------------------------------------------------
    def check_availability(
        self,
        doctor_id: int,
        from_day: date,
        days: int = 1,
        time_of_day: TimeOfDay | None = None,
        after: datetime | None = None,
        limit: int = 5,
    ) -> Availability:
        earliest = max(self.clock(), after) if after else self.clock()
        found: list[datetime] = []
        with self.session_factory() as session:
            windows = repository.get_working_windows(session, doctor_id)
            for offset in range(days):
                day = from_day + timedelta(days=offset)
                booked = repository.get_booked_starts(session, doctor_id, day, self.tz)
                for slot in free_slots(day, windows, booked, earliest, self.tz, self.slot_minutes):
                    if self._in_time_of_day(slot, time_of_day):
                        found.append(slot)
                        if len(found) >= limit:
                            return Availability(doctor_id=doctor_id, slots=found)
        return Availability(doctor_id=doctor_id, slots=found)

    def check_slot(self, doctor_id: int, start: datetime) -> SlotCheck:
        with self.session_factory() as session:
            error = self._validate(session, doctor_id, start)
        return SlotCheck(ok=error is None, error=error)

    def _validate(self, session: Session, doctor_id: int, start: datetime) -> str | None:
        day = start.astimezone(self.tz).date()
        windows = repository.get_working_windows(session, doctor_id)
        booked = repository.get_booked_starts(session, doctor_id, day, self.tz)
        error = validate_slot(start, windows, booked, self.clock(), self.tz, self.slot_minutes)
        return error.value if error else None

    # -- booking -------------------------------------------------------------------------
    def book_appointment(self, patient_id: int, doctor_id: int, start: datetime) -> BookingResult:
        """Validate, insert (the unique index decides races), then the optional calendar step."""
        start = start.astimezone(UTC)
        with self.session_factory() as session:
            doctor = repository.get_doctor(session, doctor_id)
            if doctor is None:
                return BookingResult(ok=False, error="unknown_doctor")
            if error := self._validate(session, doctor_id, start):
                return BookingResult(ok=False, error=error)
            try:
                appointment = repository.create_appointment(session, patient_id, doctor_id, start)
            except repository.SlotTakenError:
                return BookingResult(ok=False, error="already_booked")

            event_id = None
            try:  # best effort, after the commit: never undo a booking for a calendar problem
                event_id = self.calendar.add(
                    CalendarEvent(appointment.id, doctor.name, start, self.slot_minutes)
                )
            except Exception as exc:
                log.warning("calendar_add_failed: %s", type(exc).__name__)
            if event_id:
                appointment.calendar_event_id = event_id
                session.commit()
            return BookingResult(
                ok=True, appointment_id=appointment.id, start=start, calendar_event_id=event_id
            )

    def list_appointments(self, patient_id: int, upcoming_only: bool = True) -> AppointmentList:
        with self.session_factory() as session:
            after = self.clock() if upcoming_only else None
            rows = repository.list_patient_appointments(session, patient_id, after)
            return AppointmentList(
                appointments=[
                    AppointmentInfo(
                        id=a.id,
                        doctor_id=d.id,
                        doctor_name=d.name,
                        start=a.start_time,
                        status=a.status.value,
                    )
                    for a, d in rows
                ]
            )

    def cancel_appointment(self, patient_id: int, appointment_id: int) -> CancelResult:
        """Only the patient's own, booked, future appointments can be cancelled."""
        with self.session_factory() as session:
            appointment = repository.get_appointment(session, appointment_id)
            if appointment is None or appointment.patient_id != patient_id:
                return CancelResult(ok=False, error="not_found")  # don't reveal others' bookings
            if (
                appointment.status != AppointmentStatus.BOOKED
                or appointment.start_time <= self.clock()
            ):
                return CancelResult(ok=False, error="not_cancellable")
            appointment.status = AppointmentStatus.CANCELLED
            session.commit()
            had_event = appointment.calendar_event_id is not None
        if had_event:
            try:
                self.calendar.remove(appointment_id)
            except Exception as exc:
                log.warning("calendar_remove_failed: %s", type(exc).__name__)
        return CancelResult(ok=True)

    # -- OpenStreetMap -------------------------------------------------------------------
    def find_nearby_clinics(self, city: str) -> NearbyClinics:
        return self.osm.nearby_clinics(city)


class ClinicTools(Protocol):
    """What the graph needs. Async, because the MCP client is async."""

    async def get_doctor(self, doctor_id: int) -> DoctorInfo | None: ...

    async def search_doctors(
        self,
        specialty: str | None = None,
        city: str | None = None,
        language: str | None = None,
        name: str | None = None,
        limit: int = 5,
    ) -> DoctorList: ...

    async def check_availability(
        self,
        doctor_id: int,
        from_day: date,
        days: int = 1,
        time_of_day: TimeOfDay | None = None,
        after: datetime | None = None,
        limit: int = 5,
    ) -> Availability: ...

    async def check_slot(self, doctor_id: int, start: datetime) -> SlotCheck: ...

    async def book_appointment(
        self, patient_id: int, doctor_id: int, start: datetime
    ) -> BookingResult: ...

    async def list_appointments(
        self, patient_id: int, upcoming_only: bool = True
    ) -> AppointmentList: ...

    async def cancel_appointment(self, patient_id: int, appointment_id: int) -> CancelResult: ...

    async def find_nearby_clinics(self, city: str) -> NearbyClinics: ...


class LocalClinicTools:
    """In-process tools. The service is sync (SQLAlchemy), so calls run in a worker thread to
    keep the event loop free."""

    def __init__(self, service: ClinicService) -> None:
        self.service = service

    @staticmethod
    async def _run(fn: Callable[..., R], *args: object) -> R:
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception as exc:
            raise ToolError(f"{fn.__name__}: {type(exc).__name__}") from exc

    async def get_doctor(self, doctor_id: int) -> DoctorInfo | None:
        return await self._run(self.service.get_doctor, doctor_id)

    async def search_doctors(
        self,
        specialty: str | None = None,
        city: str | None = None,
        language: str | None = None,
        name: str | None = None,
        limit: int = 5,
    ) -> DoctorList:
        return await self._run(self.service.search_doctors, specialty, city, language, name, limit)

    async def check_availability(
        self,
        doctor_id: int,
        from_day: date,
        days: int = 1,
        time_of_day: TimeOfDay | None = None,
        after: datetime | None = None,
        limit: int = 5,
    ) -> Availability:
        return await self._run(
            self.service.check_availability, doctor_id, from_day, days, time_of_day, after, limit
        )

    async def check_slot(self, doctor_id: int, start: datetime) -> SlotCheck:
        return await self._run(self.service.check_slot, doctor_id, start)

    async def book_appointment(
        self, patient_id: int, doctor_id: int, start: datetime
    ) -> BookingResult:
        return await self._run(self.service.book_appointment, patient_id, doctor_id, start)

    async def list_appointments(
        self, patient_id: int, upcoming_only: bool = True
    ) -> AppointmentList:
        return await self._run(self.service.list_appointments, patient_id, upcoming_only)

    async def cancel_appointment(self, patient_id: int, appointment_id: int) -> CancelResult:
        return await self._run(self.service.cancel_appointment, patient_id, appointment_id)

    async def find_nearby_clinics(self, city: str) -> NearbyClinics:
        return await self._run(self.service.find_nearby_clinics, city)
