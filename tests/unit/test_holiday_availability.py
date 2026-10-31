"""Holidays inside the pure availability and validation services."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from medagent.services.availability import WorkingWindow, free_slots, generate_slots
from medagent.services.public_holidays import lookup_for_city
from medagent.services.validation import BookingError, validate_slot

BERLIN = ZoneInfo("Europe/Berlin")
WEEKDAYS = [WorkingWindow(d, time(8), time(12)) for d in range(5)]  # Mon-Fri 08-12
NOW = datetime(2025, 10, 27, 8, 0, tzinfo=UTC)  # Monday before Friday 31 October 2025
FRIDAY_HOLIDAY = date(2025, 10, 31)  # Reformation Day: Saxony yes, Berlin no
SUNDAY = date(2025, 11, 2)


def only(name: str | None):  # type: ignore[no-untyped-def]
    """A fake calendar that reports `name` on every day."""
    return lambda day: name


def at(day: date, hour: int = 9) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=BERLIN)


# ------------------------------------------------------------------ generate_slots / free_slots
def test_no_slots_are_generated_on_a_holiday() -> None:
    assert generate_slots(FRIDAY_HOLIDAY, WEEKDAYS, BERLIN, 30, only("Some Holiday")) == []
    assert len(generate_slots(FRIDAY_HOLIDAY, WEEKDAYS, BERLIN, 30, only(None))) == 8  # normal day


def test_a_calendar_that_names_only_one_day_closes_only_that_day() -> None:
    def calendar(day: date) -> str | None:
        return "Reformation Day" if day == FRIDAY_HOLIDAY else None

    thursday = date(2025, 10, 30)
    assert generate_slots(thursday, WEEKDAYS, BERLIN, 30, calendar)
    assert generate_slots(FRIDAY_HOLIDAY, WEEKDAYS, BERLIN, 30, calendar) == []


def test_omitting_the_calendar_keeps_the_old_behaviour() -> None:
    assert len(generate_slots(FRIDAY_HOLIDAY, WEEKDAYS, BERLIN, 30)) == 8
    assert len(free_slots(FRIDAY_HOLIDAY, WEEKDAYS, [], NOW, BERLIN, 30)) == 8


def test_free_slots_honours_the_holiday() -> None:
    leipzig = lookup_for_city("Leipzig")
    berlin = lookup_for_city("Berlin")
    assert free_slots(FRIDAY_HOLIDAY, WEEKDAYS, [], NOW, BERLIN, 30, leipzig) == []
    assert len(free_slots(FRIDAY_HOLIDAY, WEEKDAYS, [], NOW, BERLIN, 30, berlin)) == 8


# ------------------------------------------------------------------ validate_slot
def test_booking_on_a_holiday_is_rejected_with_its_own_reason() -> None:
    result = validate_slot(at(FRIDAY_HOLIDAY), WEEKDAYS, [], NOW, BERLIN, 30, only("Holiday"))
    assert result is BookingError.PUBLIC_HOLIDAY
    assert BookingError.PUBLIC_HOLIDAY.value == "public_holiday"


def test_the_same_slot_is_valid_in_a_city_without_that_holiday() -> None:
    start = at(FRIDAY_HOLIDAY)
    assert validate_slot(start, WEEKDAYS, [], NOW, BERLIN, 30, lookup_for_city("Berlin")) is None
    closed = validate_slot(start, WEEKDAYS, [], NOW, BERLIN, 30, lookup_for_city("Leipzig"))
    assert closed is BookingError.PUBLIC_HOLIDAY


def test_a_day_without_working_hours_wins_over_a_holiday() -> None:
    """A Sunday that is also a holiday still says 'not a working day': the weekday check comes
    first, so the message talks about the schedule, not the calendar."""
    result = validate_slot(at(SUNDAY), WEEKDAYS, [], NOW, BERLIN, 30, only("Holiday"))
    assert result is BookingError.NOT_A_WORKING_DAY


def test_the_past_still_wins_over_a_holiday() -> None:
    past = at(date(2025, 10, 20))
    assert validate_slot(past, WEEKDAYS, [], NOW, BERLIN, 30, only("H")) is BookingError.IN_THE_PAST


def test_a_holiday_wins_over_an_off_grid_time_or_a_booked_slot() -> None:
    off_grid = datetime.combine(FRIDAY_HOLIDAY, time(9, 15), tzinfo=BERLIN)
    booked = [at(FRIDAY_HOLIDAY)]
    for start in (off_grid, at(FRIDAY_HOLIDAY)):
        result = validate_slot(start, WEEKDAYS, booked, NOW, BERLIN, 30, only("Holiday"))
        assert result is BookingError.PUBLIC_HOLIDAY


def test_validation_without_a_calendar_is_unchanged() -> None:
    assert validate_slot(at(FRIDAY_HOLIDAY), WEEKDAYS, [], NOW, BERLIN, 30) is None
