"""German public holidays per city: the pure lookup, pinned against the library's data."""

import unicodedata
from datetime import date, timedelta

import pytest

from medagent.db.seed import CITIES
from medagent.services.public_holidays import (
    ALIASES,
    NATIONAL_ONLY,
    REGIONS,
    _calendar,
    holiday_on,
    lookup_for_city,
    region_for_city,
)

# The ten cities the clinic seeds, as (city, state) for the tables below.
SEEDED = [
    "Berlin", "Hamburg", "München", "Köln", "Frankfurt am Main",
    "Stuttgart", "Düsseldorf", "Leipzig", "Dresden", "Hannover",
]  # fmt: skip


def names(day: date, cities: list[str]) -> dict[str, str | None]:
    return {city: holiday_on(day, city) for city in cities}


# ------------------------------------------------------------------ the city table
def test_every_seeded_city_has_a_region() -> None:
    """A new city added to the seed without a table entry would silently get national holidays
    only; this makes that a failing test instead."""
    assert set(SEEDED) == set(CITIES)  # the list above is the seed's list
    missing = [city for city in CITIES if region_for_city(city) is NATIONAL_ONLY]
    assert not missing, f"add these cities to REGIONS: {missing}"


def test_table_keys_are_normalised_and_aliases_point_at_real_cities() -> None:
    for key in REGIONS:
        assert key == unicodedata.normalize("NFC", key).casefold()
    assert set(ALIASES.values()) <= set(REGIONS)


def test_the_catholic_flag_is_only_set_where_intended() -> None:
    catholic = {city for city, region in REGIONS.items() if region.catholic}
    assert catholic == {"münchen"}  # it must never be global: see the Corpus Christi test below


@pytest.mark.parametrize(
    "spelling",
    ["München", "münchen", "MÜNCHEN", "Munich", "munich", "Muenchen", "Munchen", "  München  ",
     "München"],  # last: "u" + combining diaeresis
)  # fmt: skip
def test_city_matching_ignores_case_spelling_variants_and_unicode_form(spelling: str) -> None:
    assert region_for_city(spelling) == REGIONS["münchen"]


def test_unknown_or_missing_city_gets_national_holidays_only() -> None:
    for city in (None, "", "Atlantis", "Kleinkleckersdorf"):
        assert region_for_city(city) is NATIONAL_ONLY
        assert holiday_on(date(2026, 12, 25), city) == "Christmas Day"  # national
        assert holiday_on(date(2025, 10, 31), city) is None  # regional: not applied
        assert holiday_on(date(2026, 11, 18), city) is None


# ------------------------------------------------------------------ national holidays
@pytest.mark.parametrize(
    ("day", "name"),
    [
        (date(2026, 12, 25), "Christmas Day"),
        (date(2026, 1, 1), "New Year's Day"),
        (date(2026, 4, 6), "Easter Monday"),
        (date(2026, 5, 1), "Labor Day"),
    ],
)
def test_national_holidays_close_every_city(day: date, name: str) -> None:
    assert set(names(day, SEEDED).values()) == {name}


def test_christmas_and_new_year_hold_in_every_year_and_city() -> None:
    for year in range(2024, 2036):
        for city in SEEDED:
            assert holiday_on(date(year, 12, 25), city) == "Christmas Day"
            assert holiday_on(date(year, 1, 1), city) == "New Year's Day"


def test_easter_monday_moves_with_easter() -> None:
    expected = {2025: date(2025, 4, 21), 2026: date(2026, 4, 6), 2027: date(2027, 3, 29)}
    for year, easter_monday in expected.items():
        assert holiday_on(easter_monday, "Berlin") == "Easter Monday"
        assert holiday_on(easter_monday + timedelta(days=1), "Berlin") is None
        assert holiday_on(easter_monday - timedelta(days=1), "Berlin") is None
        assert easter_monday.year == year


def test_christmas_eve_and_new_years_eve_are_not_public_holidays() -> None:
    """Many practices close, but the law does not: this is documented, not modelled."""
    for day in (date(2026, 12, 24), date(2026, 12, 31)):
        assert set(names(day, SEEDED).values()) == {None}


# ------------------------------------------------------------------ regional holidays
def test_reformation_day_31_october_leipzig_closed_berlin_open() -> None:
    friday = date(2025, 10, 31)  # a weekday, so the difference matters
    assert friday.strftime("%a") == "Fri"
    got = names(friday, SEEDED)
    assert got["Leipzig"] == got["Dresden"] == got["Hannover"] == got["Hamburg"]
    assert got["Leipzig"] == "Reformation Day"
    for open_city in ("Berlin", "München", "Köln", "Frankfurt am Main", "Stuttgart", "Düsseldorf"):
        assert got[open_city] is None, open_city


def test_the_days_around_a_holiday_are_ordinary() -> None:
    assert holiday_on(date(2025, 10, 30), "Leipzig") is None
    assert holiday_on(date(2025, 11, 1), "Leipzig") is None  # All Saints: not in Saxony


def test_corpus_christi_is_catholic_states_only_and_not_leipzig() -> None:
    """The library's 'catholic' category would add Corpus Christi to Saxony; it must stay off
    for Leipzig and Dresden, which do not observe it."""
    got = names(date(2026, 6, 4), [*SEEDED, "Nürnberg"])
    closed = {c for c, n in got.items() if n == "Corpus Christi"}
    assert closed == {"München", "Köln", "Frankfurt am Main", "Stuttgart", "Düsseldorf", "Nürnberg"}
    for open_city in ("Berlin", "Hamburg", "Leipzig", "Dresden", "Hannover"):
        assert got[open_city] is None, open_city


def test_epiphany_womens_day_and_repentance_day() -> None:
    epiphany = names(date(2026, 1, 6), SEEDED)
    assert {c for c, n in epiphany.items() if n} == {"München", "Stuttgart"}
    assert names(date(2026, 3, 8), SEEDED)["Berlin"] == "Women's Day"
    assert {c for c, n in names(date(2026, 3, 8), SEEDED).items() if n} == {"Berlin"}
    repentance = names(date(2026, 11, 18), SEEDED)
    assert {c for c, n in repentance.items() if n} == {"Leipzig", "Dresden"}
    assert repentance["Leipzig"] == "Repentance and Prayer Day"


# ------------------------------------------------------------------ Assumption Day (Bavaria)
@pytest.mark.parametrize("year_day", [date(2025, 8, 15), date(2026, 8, 15), date(2027, 8, 15)])
def test_assumption_day_15_august_münchen_closed_nürnberg_and_berlin_open(year_day: date) -> None:
    assert holiday_on(year_day, "München") == "Assumption Day"  # predominantly Catholic
    assert holiday_on(year_day, "Nürnberg") is None  # Bavaria, but not Catholic-majority
    assert holiday_on(year_day, "Berlin") is None
    for city in ("Hamburg", "Leipzig", "Köln", "Stuttgart", "Hannover"):
        assert holiday_on(year_day, city) is None


def test_bavaria_without_the_catholic_flag_has_no_assumption_day() -> None:
    """Pins the library's behaviour that the München entry exists to work around."""
    assert region_for_city("Nürnberg").subdiv == region_for_city("München").subdiv == "BY"
    assert region_for_city("Nürnberg").catholic is False


# ------------------------------------------------------------------ language, caching, binding
def test_names_can_be_returned_in_german() -> None:
    assert holiday_on(date(2025, 10, 31), "Leipzig", "de") == "Reformationstag"
    assert holiday_on(date(2026, 12, 25), "Berlin", "de") == "Erster Weihnachtstag"
    assert holiday_on(date(2026, 11, 18), "Dresden", "de") == "Buß- und Bettag"


def test_calendars_are_cached_per_region_year_and_language() -> None:
    _calendar.cache_clear()
    holiday_on(date(2026, 3, 1), "Berlin")
    holiday_on(date(2026, 9, 9), "Berlin")
    holiday_on(date(2026, 9, 9), "Berlin")
    info = _calendar.cache_info()
    assert info.misses == 1
    assert info.hits == 2


def test_lookup_for_city_binds_the_city_and_language() -> None:
    leipzig = lookup_for_city("Leipzig")
    berlin = lookup_for_city("Berlin", "de")
    assert leipzig(date(2025, 10, 31)) == "Reformation Day"
    assert berlin(date(2025, 10, 31)) is None
    assert berlin(date(2026, 12, 25)) == "Erster Weihnachtstag"
