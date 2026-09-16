"""Place-name lookup against OpenStreetMap's Nominatim.

The projects in `contracts/` do not need this: EIA-860 gives every real asset a
latitude and longitude, and those go straight onto the map. This exists for the
other direction -- moving a project to a named place while editing a deal, and
filling in a county for a contract that arrived without one.

Nominatim is a donated public service with a usage policy, so this proxies it
rather than calling from the browser: one request per second at most, an
identifying User-Agent, and results cached so panning and retyping cost
nothing. Bulk geocoding is explicitly not allowed and is not what this does.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import requests

NOMINATIM = "https://nominatim.openstreetmap.org"
USER_AGENT = "vppa-engine/0.1 (solar VPPA settlement research tool)"

# Nominatim's absolute maximum is 1 request/second from one source.
_MIN_INTERVAL_SECONDS = 1.0
_TIMEOUT_SECONDS = 10

_throttle = threading.Lock()
_last_request = 0.0

# Small in-process caches. A person retyping a search or nudging a coordinate
# should not generate a request per keystroke.
_forward_cache: dict[tuple[str, int], list[Place]] = {}
_reverse_cache: dict[tuple[float, float], Place | None] = {}


@dataclass(frozen=True)
class Place:
    display_name: str
    lat: float
    lon: float
    county: str | None = None
    state: str | None = None


def _get(path: str, params: dict) -> object:
    """One rate-limited, identified request to Nominatim."""
    global _last_request
    with _throttle:
        wait = _MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()

    response = requests.get(
        f"{NOMINATIM}{path}",
        params={**params, "format": "jsonv2"},
        headers={"User-Agent": USER_AGENT},
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _county(address: dict) -> str | None:
    """Nominatim spells a county "Dawson County"; contracts store "Dawson"."""
    county = address.get("county")
    if county and county.endswith(" County"):
        return county[: -len(" County")]
    return county


def _place(raw: dict) -> Place:
    address = raw.get("address") or {}
    return Place(
        display_name=raw.get("display_name", ""),
        lat=float(raw["lat"]),
        lon=float(raw["lon"]),
        county=_county(address),
        state=address.get("state"),
    )


def search(query: str, limit: int = 5) -> list[Place]:
    """Places matching a name, best match first. Empty query returns nothing
    rather than asking Nominatim for everything."""
    query = query.strip()
    if not query:
        return []
    key = (query.lower(), limit)
    if key in _forward_cache:
        return _forward_cache[key]

    raw = _get("/search", {"q": query, "limit": limit, "addressdetails": 1})
    places = [_place(row) for row in raw] if isinstance(raw, list) else []
    _forward_cache[key] = places
    return places


def reverse(lat: float, lon: float) -> Place | None:
    """The place containing a coordinate, or None if Nominatim has no match.

    Coordinates are rounded to ~100 m before lookup and caching: finer than
    that is below the precision EIA-860 reports anyway, and it keeps a slider
    drag from becoming a request per pixel.
    """
    key = (round(lat, 3), round(lon, 3))
    if key in _reverse_cache:
        return _reverse_cache[key]

    raw = _get("/reverse", {"lat": key[0], "lon": key[1], "addressdetails": 1})
    place = (
        _place(raw) if isinstance(raw, dict) and "lat" in raw and "error" not in raw else None
    )
    _reverse_cache[key] = place
    return place
