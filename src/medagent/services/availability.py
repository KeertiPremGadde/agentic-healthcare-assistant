"""Slot generation. Pure functions: no DB, no clock, no LLM; callers pass everything in.

Working hours are wall-clock times in the clinic timezone; every returned datetime is
timezone-aware UTC. Doing the arithmetic in local time and converting at the end is what keeps
the slots correct across daylight-saving changes.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Maps a local calendar day to the name of the public holiday on it (None = ordinary day).
# A plain function keeps these services pure: the caller decides which city's calendar to use.
HolidayLookup = Callable[[date], str | None]


@dataclass(frozen=True, slots=True)
class WorkingWindow:
    """A doctor's working block on one weekday (0 = Monday), in clinic-local time."""

    weekday: int
    start: time
    end: time


def ensure_aware(value: datetime, name: str = "datetime") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def clinic_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC [start, end) of a local calendar day, e.g. for querying that day's appointments."""
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


def generate_slots(
    day: date,
    windows: Collection[WorkingWindow],
    tz: ZoneInfo,
    slot_minutes: int,
    holiday_on: HolidayLookup | None = None,
) -> list[datetime]:
    """All bookable slot starts (UTC) on a local calendar day, ignoring bookings and the clock.

    A slot is only generated if it ends inside its working window. On a public holiday (per
    `holiday_on`) the practice is closed, so there are none.
    """
    if holiday_on is not None and holiday_on(day):
        return []
    step = timedelta(minutes=slot_minutes)
    slots: set[datetime] = set()
    for window in windows:
        if window.weekday != day.weekday():
            continue
        current = datetime.combine(day, window.start)  # naive local wall-clock time
        end = datetime.combine(day, window.end)
        while current + step <= end:
            aware = current.replace(tzinfo=tz)
            utc = aware.astimezone(UTC)
            # Skip wall-clock times that do not exist (spring-forward gap).
            if utc.astimezone(tz).replace(tzinfo=None) == current:
                slots.add(utc)
            current += step
    return sorted(slots)


def free_slots(
    day: date,
    windows: Collection[WorkingWindow],
    booked: Collection[datetime],
    now: datetime,
    tz: ZoneInfo,
    slot_minutes: int,
    holiday_on: HolidayLookup | None = None,
) -> list[datetime]:
    """Slots on `day` that are in the future and not already booked."""
    ensure_aware(now, "now")
    taken = {ensure_aware(b, "booked").astimezone(UTC) for b in booked}
    return [
        slot
        for slot in generate_slots(day, windows, tz, slot_minutes, holiday_on)
        if slot > now and slot not in taken
    ]
