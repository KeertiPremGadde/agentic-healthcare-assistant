from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from medagent.core.config import Settings
from medagent.integrations import calendar as calendar_module
from medagent.integrations.calendar import (
    CalendarEvent,
    GoogleCalendar,
    NullCalendar,
    calendar_from_settings,
    event_id_for,
)


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_event_ids_are_valid_for_google_and_stable() -> None:
    event_id = event_id_for(42)
    assert event_id == "medagent00000042"
    assert set(event_id) <= set("abcdefghijklmnopqrstuv0123456789")  # base32hex
    assert 5 <= len(event_id) <= 1024


def test_no_settings_means_no_calendar() -> None:
    assert isinstance(calendar_from_settings(_settings()), NullCalendar)


def test_primary_calendar_id_is_rejected(tmp_path: Path) -> None:
    key = tmp_path / "sa.json"
    key.write_text("{}")
    settings = _settings(google_service_account_file=str(key), google_calendar_id="primary")
    assert isinstance(calendar_from_settings(settings), NullCalendar)


def test_missing_key_file_means_no_calendar(tmp_path: Path) -> None:
    settings = _settings(
        google_service_account_file=str(tmp_path / "missing.json"),
        google_calendar_id="abc@group.calendar.google.com",
    )
    assert isinstance(calendar_from_settings(settings), NullCalendar)


def test_null_calendar_is_a_harmless_no_op() -> None:
    calendar = NullCalendar()
    assert (
        calendar.add(CalendarEvent(1, "Dr. X", datetime(2026, 11, 3, 12, tzinfo=UTC), 30)) is None
    )
    assert calendar.remove(1) is True
    assert calendar.enabled is False


class _Request:
    def __init__(self, error_status: int | None = None) -> None:
        self.error_status = error_status

    def execute(self) -> dict[str, Any]:
        if self.error_status:
            from googleapiclient.errors import HttpError

            resp = type("Resp", (), {"status": self.error_status, "reason": "x"})()
            raise HttpError(resp, b"{}")
        return {}


class _FakeEvents:
    def __init__(self, error_status: int | None = None) -> None:
        self.inserted: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.error_status = error_status

    def insert(self, calendarId: str, body: dict[str, Any]) -> _Request:  # noqa: N803
        self.inserted.append({"calendarId": calendarId, **body})
        return _Request(self.error_status)

    def delete(self, calendarId: str, eventId: str) -> _Request:  # noqa: N803
        self.deleted.append(eventId)
        return _Request(self.error_status)


def _google(events: _FakeEvents) -> GoogleCalendar:
    calendar = GoogleCalendar.__new__(GoogleCalendar)  # skip credential loading
    calendar._events = events
    calendar._calendar_id = "demo@group.calendar.google.com"
    calendar._timezone = "Europe/Berlin"
    return calendar


def test_google_event_has_no_patient_data_and_a_deterministic_id() -> None:
    events = _FakeEvents()
    start = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    event_id = _google(events).add(CalendarEvent(7, "Dr. Michael Johnson", start, 30))
    (body,) = events.inserted
    assert event_id == body["id"] == "medagent00000007"
    assert body["summary"] == "Appointment - Dr. Michael Johnson (#A-0007)"
    assert body["start"]["timeZone"] == "Europe/Berlin"
    assert body["end"]["dateTime"] == "2026-11-03T12:30:00+00:00"
    assert "patient" not in str(body).lower()
    assert "@" not in body["summary"] + body["description"]


@pytest.mark.parametrize("status", [409])
def test_inserting_the_same_event_twice_is_idempotent(status: int) -> None:
    start = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    assert _google(_FakeEvents(status)).add(CalendarEvent(7, "Dr. X", start, 30)) == event_id_for(7)


@pytest.mark.parametrize("status", [404, 410])
def test_removing_an_already_deleted_event_counts_as_removed(status: int) -> None:
    assert _google(_FakeEvents(status)).remove(7) is True


def test_other_google_errors_propagate_to_the_best_effort_caller() -> None:
    from googleapiclient.errors import HttpError

    start = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    with pytest.raises(HttpError):
        _google(_FakeEvents(403)).add(CalendarEvent(7, "Dr. X", start, 30))
    assert calendar_module.SCOPES == ["https://www.googleapis.com/auth/calendar.events"]
