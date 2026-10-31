"""Booking validation. Returns a typed error code, never a free-text string:
the caller (API, agent tool) decides how to word it."""

import enum
from collections.abc import Collection
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from medagent.services.availability import (
    HolidayLookup,
    WorkingWindow,
    ensure_aware,
    generate_slots,
)


class BookingError(enum.StrEnum):
    IN_THE_PAST = "in_the_past"
    NOT_A_WORKING_DAY = "not_a_working_day"  # no working hours on that weekday
    PUBLIC_HOLIDAY = "public_holiday"  # a working weekday, but the practice is closed
    OUTSIDE_WORKING_HOURS = "outside_working_hours"  # also: not aligned to the slot grid
    ALREADY_BOOKED = "already_booked"


def validate_slot(
    start: datetime,
    windows: Collection[WorkingWindow],
    booked: Collection[datetime],
    now: datetime,
    tz: ZoneInfo,
    slot_minutes: int,
    holiday_on: HolidayLookup | None = None,
) -> BookingError | None:
    """Return why `start` cannot be booked, or None if it can."""
    ensure_aware(start, "start")
    ensure_aware(now, "now")
    start_utc = start.astimezone(UTC)

    if start_utc <= now:
        return BookingError.IN_THE_PAST

    local_day = start_utc.astimezone(tz).date()
    if not any(w.weekday == local_day.weekday() for w in windows):
        return BookingError.NOT_A_WORKING_DAY

    # After the weekday check, so a Sunday that is also a holiday still says "not a working day".
    if holiday_on is not None and holiday_on(local_day):
        return BookingError.PUBLIC_HOLIDAY

    if start_utc not in generate_slots(local_day, windows, tz, slot_minutes):
        return BookingError.OUTSIDE_WORKING_HOURS

    if start_utc in {ensure_aware(b, "booked").astimezone(UTC) for b in booked}:
        return BookingError.ALREADY_BOOKED
    return None
