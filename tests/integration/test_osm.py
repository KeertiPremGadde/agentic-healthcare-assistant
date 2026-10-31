"""OpenStreetMap client: parsing, 24 h Postgres cache, stale-on-error, backoff, usage policy.
No network: HTTP is served by httpx.MockTransport from a hand-written Overpass fixture."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from medagent.integrations import osm
from medagent.integrations.osm import OSMClient, parse_overpass

pytestmark = pytest.mark.integration

OVERPASS = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "overpass_sample.json").read_text()
)
NOMINATIM = [{"lat": "53.5503", "lon": "10.0007", "display_name": "Hamburg, Deutschland"}]


class FakeOSM:
    """Serves Nominatim and Overpass; records requests; can fail or rate-limit."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.overpass_statuses: list[int] = []  # statuses to return before succeeding
        self.down = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            return httpx.Response(503)
        if request.url.host == "nominatim.openstreetmap.org":
            if request.url.params.get("q") == "Atlantis":
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=NOMINATIM)
        if self.overpass_statuses:
            return httpx.Response(self.overpass_statuses.pop(0), headers={"Retry-After": "1"})
        return httpx.Response(200, json=OVERPASS)


@pytest.fixture
def fake() -> FakeOSM:
    return FakeOSM()


@pytest.fixture
def clock() -> dict[str, datetime]:
    return {"now": datetime(2026, 11, 2, 8, 0, tzinfo=UTC)}


@pytest.fixture
def client(engine: Engine, session: Any, fake: FakeOSM, clock: dict[str, datetime]) -> OSMClient:
    http = httpx.Client(transport=httpx.MockTransport(fake), headers={"User-Agent": osm.USER_AGENT})
    return OSMClient(
        sessionmaker(bind=engine), http=http, clock=lambda: clock["now"], sleep=lambda s: None
    )


def test_parse_overpass_skips_unnamed_and_orders_by_kind() -> None:
    clinics = parse_overpass(OVERPASS)
    assert [c.name for c in clinics] == [
        "Beispiel-Klinikum",  # hospital first
        "Ambulantes Zentrum Muster",  # then clinics
        "Praxis am Testweg",  # then practices
    ]
    hospital, _, practice = clinics
    assert (hospital.lat, hospital.lon) == (53.5601, 9.9902)  # way -> its center
    assert hospital.osm_url == "https://www.openstreetmap.org/way/2002"
    assert practice.address == "Testweg 5, 20095 Hamburg"


def test_fetches_once_then_serves_from_cache_for_24h(
    client: OSMClient, fake: FakeOSM, clock: dict[str, datetime]
) -> None:
    first = client.nearby_clinics("Hamburg")
    assert not first.from_cache
    assert len(first.clinics) == 3
    assert first.bookable is False
    assert "OpenStreetMap contributors" in first.attribution
    assert len(fake.requests) == 2  # one Nominatim + one Overpass
    assert all(r.headers["User-Agent"] == osm.USER_AGENT for r in fake.requests)

    clock["now"] += timedelta(hours=23)
    again = client.nearby_clinics("  hamburg ")  # normalised cache key
    assert again.from_cache
    assert len(fake.requests) == 2  # no new upstream calls

    clock["now"] += timedelta(hours=2)  # older than 24 h: refreshed
    assert not client.nearby_clinics("Hamburg").from_cache
    assert len(fake.requests) == 4


def test_stale_cache_beats_nothing_when_upstream_is_down(
    client: OSMClient, fake: FakeOSM, clock: dict[str, datetime]
) -> None:
    client.nearby_clinics("Hamburg")
    clock["now"] += timedelta(days=3)
    fake.down = True
    stale = client.nearby_clinics("Hamburg")
    assert stale.from_cache
    assert len(stale.clinics) == 3
    assert stale.error is None


def test_upstream_down_and_no_cache_returns_an_error_not_an_exception(
    client: OSMClient, fake: FakeOSM
) -> None:
    fake.down = True
    result = client.nearby_clinics("Berlin")
    assert result.clinics == []
    assert result.error == "HTTPStatusError"


def test_backs_off_once_on_429_then_succeeds(client: OSMClient, fake: FakeOSM) -> None:
    fake.overpass_statuses = [429]
    result = client.nearby_clinics("Hamburg")
    assert len(result.clinics) == 3
    overpass_calls = [r for r in fake.requests if r.url.host == "overpass-api.de"]
    assert len(overpass_calls) == 2


def test_unknown_place(client: OSMClient) -> None:
    result = client.nearby_clinics("Atlantis")
    assert result.clinics == []
    assert result.error == "OSMError"


def test_overpass_query_is_small_and_bounded() -> None:
    query = osm._overpass_query(53.55, 10.0)
    assert "[timeout:25]" in query  # the server aborts long queries
    assert "around" not in query  # bounding boxes use the spatial index
    assert query.count('["name"]') == len(osm.KINDS)  # only named places, exact tag matches
    assert query.count("out center tags") == len(osm.KINDS)  # a cap per kind
    assert query.index('"hospital"') < query.index('"doctors"')  # hospitals first
    south, west, north, east = (float(x) for x in osm._bbox(53.55, 10.0).split(","))
    assert south < 53.55 < north
    assert west < 10.0 < east
    assert round((north - south) * 111_320) == 2 * osm.RADIUS_M


def test_overpass_timeout_remark_is_an_error_not_an_empty_result(
    client: OSMClient, fake: FakeOSM, monkeypatch: pytest.MonkeyPatch
) -> None:
    timed_out = {"elements": [], "remark": 'runtime error: Query timed out in "query" at line 1'}
    monkeypatch.setattr(osm, "parse_overpass", osm.parse_overpass)  # unchanged; clarity only
    original = fake.__call__

    def timing_out(request: httpx.Request) -> httpx.Response:
        if request.url.host == "overpass-api.de":
            fake.requests.append(request)
            return httpx.Response(200, json=timed_out)
        return original(request)

    client._http = httpx.Client(transport=httpx.MockTransport(timing_out))
    result = client.nearby_clinics("Hamburg")
    assert result.clinics == []
    assert result.error == "OSMError"  # not "no clinics here"
