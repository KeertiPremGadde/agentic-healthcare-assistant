"""Optional Google Calendar integration: one shared demo calendar, written by a service account.

Design (ADR 0007):
- Optional: without credentials a `NullCalendar` is used and booking works unchanged.
- Best-effort, after the database commit: a calendar failure never undoes a booking.
- Idempotent: the event id is derived from the appointment id, so a retry can't duplicate it.
- Minimal data: doctor and confirmation number only. No patient name, email or symptoms.
- Least privilege: the `calendar.events` scope only.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from medagent.core.config import Settings

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


@dataclass(frozen=True)
class CalendarEvent:
    appointment_id: int
    doctor_name: str
    start: datetime  # timezone-aware
    minutes: int


def event_id_for(appointment_id: int) -> str:
    """Google allows client-chosen ids: 5-1024 chars from a-v and 0-9 (base32hex)."""
    return f"medagent{appointment_id:08d}"


class Calendar(Protocol):
    enabled: bool

    def add(self, event: CalendarEvent) -> str | None: ...

    def remove(self, appointment_id: int) -> bool: ...


class NullCalendar:
    """Used when no calendar is configured: every call is a successful no-op."""

    enabled = False

    def add(self, event: CalendarEvent) -> str | None:
        return None

    def remove(self, appointment_id: int) -> bool:
        return True


class GoogleCalendar:
    enabled = True

    def __init__(self, service_account_file: str, calendar_id: str, timezone: str) -> None:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            service_account_file, scopes=SCOPES
        )
        self._events: Any = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        ).events()
        self._calendar_id = calendar_id
        self._timezone = timezone

    def add(self, event: CalendarEvent) -> str | None:
        from googleapiclient.errors import HttpError

        event_id = event_id_for(event.appointment_id)
        end = event.start + timedelta(minutes=event.minutes)
        body = {
            "id": event_id,
            "summary": f"Appointment - {event.doctor_name} (#A-{event.appointment_id:04d})",
            "description": "Booked via MedAgent (demo). Synthetic data only.",
            "start": {"dateTime": event.start.isoformat(), "timeZone": self._timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": self._timezone},
        }
        try:
            self._events.insert(calendarId=self._calendar_id, body=body).execute()
        except HttpError as exc:
            if exc.resp.status != 409:  # 409 = already exists: a retry, which is fine
                raise
        return event_id

    def remove(self, appointment_id: int) -> bool:
        from googleapiclient.errors import HttpError

        try:
            self._events.delete(
                calendarId=self._calendar_id, eventId=event_id_for(appointment_id)
            ).execute()
        except HttpError as exc:
            if exc.resp.status not in (404, 410):  # already gone counts as removed
                raise
        return True


def calendar_from_settings(settings: Settings) -> Calendar:
    """GoogleCalendar if fully configured, otherwise NullCalendar (with a reason in the log)."""
    key_file, calendar_id = settings.google_service_account_file, settings.google_calendar_id
    if not key_file or not calendar_id:
        return NullCalendar()
    if calendar_id == "primary":
        log.warning(
            "calendar_disabled: GOOGLE_CALENDAR_ID=primary is the service account's own, invisible "
            "calendar; use the shared demo calendar's ID"
        )
        return NullCalendar()
    if not Path(key_file).is_file():
        log.warning("calendar_disabled: GOOGLE_SERVICE_ACCOUNT_FILE does not exist")
        return NullCalendar()
    return GoogleCalendar(key_file, calendar_id, settings.clinic_timezone)
