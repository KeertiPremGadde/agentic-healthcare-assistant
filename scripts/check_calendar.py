"""Check the optional Google Calendar setup: create one test event in the demo calendar, then
delete it. Prints only success/failure, never credentials or the calendar ID.

    uv run python scripts/check_calendar.py
"""

from datetime import UTC, datetime, timedelta

from medagent.core.config import get_settings
from medagent.integrations.calendar import CalendarEvent, calendar_from_settings

TEST_APPOINTMENT_ID = 99_999_999  # never a real appointment id; event id medagent99999999


def main() -> None:
    calendar = calendar_from_settings(get_settings())
    if not calendar.enabled:
        raise SystemExit(
            "Calendar not configured (or misconfigured): booking will skip the calendar step.\n"
            "Set GOOGLE_SERVICE_ACCOUNT_FILE (a file in secrets/) and GOOGLE_CALENDAR_ID "
            "(the shared demo calendar, not 'primary') in .env."
        )
    start = (datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    event = CalendarEvent(TEST_APPOINTMENT_ID, "Dr. Calendar Check", start, 30)
    try:
        event_id = calendar.add(event)
        print(f"created test event {event_id}: OK")
        calendar.remove(TEST_APPOINTMENT_ID)
        print("deleted test event: OK")
    except Exception as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        hint = {
            403: "the service account can't write: share the calendar with its email "
            "('Make changes to events')",
            404: "calendar not found: check GOOGLE_CALENDAR_ID (Settings > Integrate calendar)",
        }.get(status or 0, "see the error type")
        message = f"Calendar check FAILED ({type(exc).__name__}, HTTP {status}): {hint}"
        raise SystemExit(message) from None  # no traceback: it could include request details
    print("Google Calendar integration works.")


if __name__ == "__main__":
    main()
