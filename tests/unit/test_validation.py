from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from medagent.services.availability import WorkingWindow
from medagent.services.validation import BookingError, validate_slot

BERLIN = ZoneInfo("Europe/Berlin")
WINDOWS = [WorkingWindow(d, time(8), time(17)) for d in range(5)]  # Mon-Fri 08-17
NOW = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)  # Monday 07:00 Berlin


def check(start: datetime, booked: list[datetime] | None = None) -> BookingError | None:
    return validate_slot(start, WINDOWS, booked or [], NOW, BERLIN, 30)


def berlin(*args: int) -> datetime:
    return datetime(*args, tzinfo=BERLIN)


def test_valid_slot_passes() -> None:
    assert check(berlin(2026, 11, 3, 10, 0)) is None


def test_past_slot_rejected() -> None:
    assert check(berlin(2026, 11, 2, 6, 0)) is BookingError.IN_THE_PAST
    assert check(NOW) is BookingError.IN_THE_PAST  # exactly now is not in the future


def test_weekend_rejected_as_not_a_working_day() -> None:
    assert check(berlin(2026, 11, 7, 10, 0)) is BookingError.NOT_A_WORKING_DAY  # Saturday


@pytest.mark.parametrize(
    ("hour", "minute"),
    [(7, 30), (17, 0), (16, 45), (10, 15)],  # before open, at close, last-slot overrun, off-grid
)
def test_outside_hours_or_off_grid_rejected(hour: int, minute: int) -> None:
    assert check(berlin(2026, 11, 3, hour, minute)) is BookingError.OUTSIDE_WORKING_HOURS


def test_last_slot_of_the_day_is_valid() -> None:
    assert check(berlin(2026, 11, 3, 16, 30)) is None


def test_already_booked_rejected() -> None:
    slot = berlin(2026, 11, 3, 10, 0)
    assert check(slot, booked=[slot]) is BookingError.ALREADY_BOOKED


def test_working_hours_are_interpreted_in_clinic_timezone_not_utc() -> None:
    # 07:30 UTC on Tuesday is 08:30 in Berlin -> inside hours. Naive UTC logic would say 07:30.
    assert check(datetime(2026, 11, 3, 7, 30, tzinfo=UTC)) is None
    # 06:30 UTC is 07:30 Berlin -> before opening.
    assert check(datetime(2026, 11, 3, 6, 30, tzinfo=UTC)) is BookingError.OUTSIDE_WORKING_HOURS


def test_day_boundary_uses_local_date() -> None:
    # Sunday 23:30 UTC is Monday 00:30 in Berlin: a working day, but outside hours.
    sunday_night_utc = datetime(2026, 11, 8, 23, 30, tzinfo=UTC)
    assert check(sunday_night_utc) is BookingError.OUTSIDE_WORKING_HOURS


def test_naive_start_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        check(datetime(2026, 11, 3, 10, 0))
