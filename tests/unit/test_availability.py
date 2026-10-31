from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from medagent.services.availability import (
    WorkingWindow,
    clinic_day_bounds,
    free_slots,
    generate_slots,
)

BERLIN = ZoneInfo("Europe/Berlin")
MONDAY = date(2026, 11, 2)  # winter: Berlin = UTC+1
MONDAY_SUMMER = date(2026, 7, 6)  # summer: Berlin = UTC+2
WORKDAY = [WorkingWindow(0, time(8), time(12)), WorkingWindow(0, time(13), time(17))]


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_slots_are_local_wall_clock_converted_to_utc_winter() -> None:
    slots = generate_slots(MONDAY, WORKDAY, BERLIN, 30)
    assert slots[0] == utc(2026, 11, 2, 7, 0)  # 08:00 CET
    assert slots[-1] == utc(2026, 11, 2, 15, 30)  # 16:30 CET, last 30-min slot before 17:00


def test_slots_follow_daylight_saving_in_summer() -> None:
    slots = generate_slots(MONDAY_SUMMER, WORKDAY, BERLIN, 30)
    assert slots[0] == utc(2026, 7, 6, 6, 0)  # 08:00 CEST


def test_lunch_break_has_no_slots() -> None:
    slots = {s.astimezone(BERLIN).time() for s in generate_slots(MONDAY, WORKDAY, BERLIN, 30)}
    assert time(12, 0) not in slots
    assert time(12, 30) not in slots
    assert time(13, 0) in slots
    assert len(slots) == 8 + 8


def test_no_slots_on_days_without_a_window() -> None:
    saturday = date(2026, 11, 7)
    assert generate_slots(saturday, WORKDAY, BERLIN, 30) == []


def test_slot_must_end_inside_the_window() -> None:
    window = [WorkingWindow(0, time(8), time(9, 15))]
    slots = generate_slots(MONDAY, window, BERLIN, 30)
    assert [s.astimezone(BERLIN).time() for s in slots] == [time(8, 0), time(8, 30)]


def test_overlapping_windows_do_not_duplicate_slots() -> None:
    windows = [WorkingWindow(0, time(8), time(10)), WorkingWindow(0, time(9), time(11))]
    slots = generate_slots(MONDAY, windows, BERLIN, 30)
    assert len(slots) == len(set(slots)) == 6


def test_nonexistent_wall_clock_time_is_skipped_on_spring_forward() -> None:
    # 2027-03-28 (Sunday): clocks jump 02:00 -> 03:00 in Berlin, so 02:00 and 02:30 don't exist.
    window = [WorkingWindow(6, time(1), time(4))]
    slots = generate_slots(date(2027, 3, 28), window, BERLIN, 30)
    local = [s.astimezone(BERLIN).time() for s in slots]
    assert local == [time(1, 0), time(1, 30), time(3, 0), time(3, 30)]


def test_day_bounds_are_a_utc_range_covering_the_local_day() -> None:
    lo, hi = clinic_day_bounds(MONDAY, BERLIN)
    assert lo == utc(2026, 11, 1, 23, 0)
    assert hi == utc(2026, 11, 2, 23, 0)
    # On the 23-hour spring-forward day the range is 23 hours long.
    lo, hi = clinic_day_bounds(date(2027, 3, 28), BERLIN)
    assert (hi - lo).total_seconds() == 23 * 3600


def test_free_slots_remove_booked_and_past_slots() -> None:
    now = utc(2026, 11, 2, 8, 0)  # 09:00 Berlin
    booked = [utc(2026, 11, 2, 9, 0)]  # 10:00 Berlin
    slots = free_slots(MONDAY, WORKDAY, booked, now, BERLIN, 30)
    local = [s.astimezone(BERLIN).time() for s in slots]
    assert time(9, 0) not in local  # now (not strictly in the future)
    assert time(8, 30) not in local  # past
    assert time(10, 0) not in local  # booked
    assert time(9, 30) in local
    assert time(10, 30) in local


def test_free_slots_accept_booked_times_in_any_timezone() -> None:
    now = utc(2026, 11, 1, 12, 0)
    booked = [datetime(2026, 11, 2, 8, 0, tzinfo=BERLIN)]  # == 07:00 UTC
    slots = free_slots(MONDAY, WORKDAY, booked, now, BERLIN, 30)
    assert utc(2026, 11, 2, 7, 0) not in slots


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        free_slots(MONDAY, WORKDAY, [], datetime(2026, 11, 1, 12, 0), BERLIN, 30)
