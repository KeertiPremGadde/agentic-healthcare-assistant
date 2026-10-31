"""German public holidays per city (pure: no I/O, no clock, no database).

German public holidays are set by the federal states, and a few depend on the municipality, so a
doctor's practice is closed on the holidays of *its city*, not of "Germany". Each city maps to a
`Region`: the state (ISO 3166-2 code) plus whether the municipality is predominantly Catholic.

The `holidays` library models the Catholic exception as a separate category: for Bavaria it adds
Assumption Day (15 August), which München observes and Nürnberg does not. That category must be
switched on per city, never globally: it also adds Corpus Christi to Saxony and Thuringia, which
Leipzig and Dresden do not observe.

Not modelled (documented in ADR 0010): practice holidays and personal time off, bridge days,
24 and 31 December (not public holidays), school holidays, and further municipal exceptions.
Data comes from the open-source `holidays` library (MIT); it is not an official calendar.
"""

import unicodedata
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import holidays

from medagent.services.availability import HolidayLookup

SUPPORTED_LANGUAGES = ("en_US", "de")


@dataclass(frozen=True, slots=True)
class Region:
    subdiv: str | None  # state code such as "BE"; None = national holidays only
    catholic: bool = False  # predominantly Catholic municipality (adds Assumption Day in Bavaria)


# Every city the clinic seeds (tests enforce completeness), plus Nürnberg as the contrast to
# München. Keys are lower-case; see `region_for_city` for the matching rules.
REGIONS: dict[str, Region] = {
    "berlin": Region("BE"),
    "hamburg": Region("HH"),
    "münchen": Region("BY", catholic=True),  # observes Assumption Day
    "köln": Region("NW"),
    "frankfurt am main": Region("HE"),
    "stuttgart": Region("BW"),
    "düsseldorf": Region("NW"),
    "leipzig": Region("SN"),
    "dresden": Region("SN"),
    "hannover": Region("NI"),
    "nürnberg": Region("BY"),  # Bavaria, but not a predominantly Catholic municipality
}

# Common ASCII and English spellings of the same cities.
ALIASES = {
    "munich": "münchen",
    "muenchen": "münchen",
    "munchen": "münchen",
    "cologne": "köln",
    "koeln": "köln",
    "duesseldorf": "düsseldorf",
    "dusseldorf": "düsseldorf",
    "nuremberg": "nürnberg",
    "nuernberg": "nürnberg",
    "frankfurt": "frankfurt am main",
    "hanover": "hannover",
}

NATIONAL_ONLY = Region(None)


def _key(city: str) -> str:
    return unicodedata.normalize("NFC", city).strip().casefold()


def region_for_city(city: str | None) -> Region:
    """The city's region; an unknown or missing city gets the national holidays only."""
    if not city:
        return NATIONAL_ONLY
    key = _key(city)
    return REGIONS.get(ALIASES.get(key, key), NATIONAL_ONLY)


@lru_cache(maxsize=512)
def _calendar(subdiv: str | None, catholic: bool, year: int, language: str) -> holidays.HolidayBase:
    categories = ("public", "catholic") if catholic else ("public",)
    return holidays.country_holidays(
        "DE", subdiv=subdiv, years=year, categories=categories, language=language
    )


def holiday_on(day: date, city: str | None, language: str = "en_US") -> str | None:
    """The public holiday's name on `day` for this city, or None if it is an ordinary day."""
    region = region_for_city(city)
    return _calendar(region.subdiv, region.catholic, day.year, language).get(day)


def lookup_for_city(city: str | None, language: str = "en_US") -> HolidayLookup:
    """`holiday_on` bound to one city, in the shape the availability services expect."""

    def lookup(day: date) -> str | None:
        return holiday_on(day, city, language)

    return lookup
