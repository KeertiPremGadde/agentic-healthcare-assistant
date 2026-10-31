"""Nearby clinics from OpenStreetMap: Nominatim (city -> coordinates) + Overpass (amenities).

Usage policies respected (https://operations.osmfoundation.org/policies/nominatim/ and the
Overpass API guidelines): an identifying User-Agent, at most one Nominatim request per second,
small bounding-box queries with a server-side timeout, one retry with backoff on 429/504, and a
24-hour cache so repeated questions never reach the public servers. Results are ODbL data and
are always returned with attribution. They are real places and are never bookable.

The public Overpass instance is shared and can be slow under load (measured 30-40 s for this
query on a busy evening), hence the 60 s read timeout and the configurable endpoint
(`OVERPASS_URL`) for a mirror or self-hosted instance.
"""

import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from medagent.db.models import ExternalCache
from medagent.tools.models import NearbyClinic, NearbyClinics

USER_AGENT = (
    "MedAgent-portfolio/0.4 (+https://github.com/KeertiPremGadde/agentic-healthcare-assistant)"
)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CACHE_TTL = timedelta(hours=24)
RADIUS_M = 3000
MAX_RESULTS = 10
# Per-kind caps, hospitals first. One global cap would cut kinds arbitrarily, because Overpass
# sorts output by element id, not by kind.
KIND_LIMITS = {"hospital": 10, "clinic": 15, "doctors": 15}
KINDS = tuple(KIND_LIMITS)
QUERY_VERSION = "v2"  # part of the cache key: bump when the query changes

_nominatim_lock = threading.Lock()
_last_nominatim_call = 0.0


class OSMError(Exception):
    pass


def _bbox(lat: float, lon: float, radius_m: int = RADIUS_M) -> str:
    """south,west,north,east around a point (bounding boxes use Overpass's spatial index)."""
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    return f"{lat - dlat:.5f},{lon - dlon:.5f},{lat + dlat:.5f},{lon + dlon:.5f}"


def _overpass_query(lat: float, lon: float) -> str:
    # Exact tag matches in a bounding box (index-friendly), one capped `out` per kind.
    bbox = _bbox(lat, lon)
    parts = "".join(
        f'nwr["amenity"="{kind}"]["name"]({bbox});out center tags {limit};'
        for kind, limit in KIND_LIMITS.items()
    )
    return f"[out:json][timeout:25];{parts}"


def _check_overpass(payload: dict[str, Any]) -> dict[str, Any]:
    """Overpass reports query timeouts as HTTP 200 with an empty result and a `remark`."""
    remark = str(payload.get("remark", ""))
    if "error" in remark.lower() or "timed out" in remark.lower():
        raise OSMError("overpass query failed")
    return payload


def _address(tags: dict[str, str]) -> str | None:
    street = " ".join(p for p in (tags.get("addr:street"), tags.get("addr:housenumber")) if p)
    city = " ".join(p for p in (tags.get("addr:postcode"), tags.get("addr:city")) if p)
    return ", ".join(p for p in (street, city) if p) or None


def parse_overpass(payload: dict[str, Any]) -> list[NearbyClinic]:
    clinics: list[NearbyClinic] = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        lat = element.get("lat", (element.get("center") or {}).get("lat"))
        lon = element.get("lon", (element.get("center") or {}).get("lon"))
        if not tags.get("name") or lat is None or lon is None:
            continue
        clinics.append(
            NearbyClinic(
                name=tags["name"],
                kind=tags.get("amenity", "clinic"),
                address=_address(tags),
                website=tags.get("website") or tags.get("contact:website"),
                lat=float(lat),
                lon=float(lon),
                osm_url=f"https://www.openstreetmap.org/{element['type']}/{element['id']}",
            )
        )
    # Hospitals and clinics before single practices, then alphabetically: stable output.
    order = {"hospital": 0, "clinic": 1, "doctors": 2}
    clinics.sort(key=lambda c: (order.get(c.kind, 3), c.name))
    return clinics[:MAX_RESULTS]


class OSMClient:
    def __init__(
        self,
        session_factory: Callable[[], Any],
        http: httpx.Client | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
        overpass_url: str = OVERPASS_URL,
    ) -> None:
        self._session_factory = session_factory
        self._http = http or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(10, read=60)
        )
        self._overpass_url = overpass_url
        self._clock = clock
        self._sleep = sleep

    # -- cache ---------------------------------------------------------------------------
    def _cache_get(self, session: Session, key: str) -> tuple[dict[str, Any], bool] | None:
        """Return (payload, fresh) or None."""
        row = session.get(ExternalCache, key)
        if row is None:
            return None
        return row.payload, self._clock() - row.fetched_at < CACHE_TTL

    def _cache_put(self, session: Session, key: str, payload: dict[str, Any]) -> None:
        stmt = insert(ExternalCache).values(key=key, payload=payload, fetched_at=self._clock())
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[ExternalCache.key],
                set_={"payload": stmt.excluded.payload, "fetched_at": stmt.excluded.fetched_at},
            )
        )
        session.commit()

    # -- upstream calls ------------------------------------------------------------------
    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        for attempt in range(2):
            response = self._http.request(method, url, **kwargs)
            if response.status_code in (429, 504) and attempt == 0:
                self._sleep(float(response.headers.get("Retry-After", 5)))  # back off once
                continue
            response.raise_for_status()
            return response.json()
        raise OSMError("upstream busy")  # pragma: no cover

    def _geocode(self, city: str) -> tuple[float, float]:
        global _last_nominatim_call
        with _nominatim_lock:  # at most one request per second, process-wide
            wait = 1.0 - (time.monotonic() - _last_nominatim_call)
            if wait > 0:
                self._sleep(wait)
            _last_nominatim_call = time.monotonic()
            results = self._request(
                "GET", NOMINATIM_URL, params={"q": city, "format": "jsonv2", "limit": 1}
            )
        if not results:
            raise OSMError(f"unknown place: {city}")
        return float(results[0]["lat"]), float(results[0]["lon"])

    # -- public --------------------------------------------------------------------------
    def nearby_clinics(self, city: str) -> NearbyClinics:
        key = f"osm:clinics:{QUERY_VERSION}:{city.strip().lower()}:{RADIUS_M}"
        with self._session_factory() as session:
            cached = self._cache_get(session, key)
            if cached and cached[1]:
                return NearbyClinics(city=city, clinics=parse_overpass(cached[0]), from_cache=True)
            try:
                lat, lon = self._geocode(city)
                payload = self._request(
                    "POST", self._overpass_url, data={"data": _overpass_query(lat, lon)}
                )
                _check_overpass(payload)
            except (httpx.HTTPError, OSMError, KeyError, ValueError) as exc:
                if cached:  # stale beats nothing when the public servers are busy
                    return NearbyClinics(
                        city=city, clinics=parse_overpass(cached[0]), from_cache=True
                    )
                return NearbyClinics(city=city, clinics=[], error=type(exc).__name__)
            self._cache_put(session, key, payload)
        return NearbyClinics(city=city, clinics=parse_overpass(payload))
