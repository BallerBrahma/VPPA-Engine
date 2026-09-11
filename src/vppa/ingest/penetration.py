"""EIA-860 nearby solar capacity, aggregated by year, for capture-rate decay."""

from __future__ import annotations

import math
import os

import pandas as pd
import requests
from dotenv import load_dotenv

from vppa import store

load_dotenv()

EIA_GENERATOR_CAPACITY_URL = (
    "https://api.eia.gov/v2/electricity/operating-generator-capacity/data/"
)

# The snapshot period to pull the fleet as of. Each generator row carries its
# own operating-year-month, so one recent snapshot supports every historical
# year -- capacity is rolled forward from in-service dates rather than
# re-queried per year.
FLEET_SNAPSHOT_PERIOD = "2026-06"

EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: pd.Series, lon2: pd.Series) -> pd.Series:
    """Great-circle distance in km from one point to many."""
    phi1, phi2 = math.radians(lat1), pd.Series(lat2).map(math.radians)
    dphi = phi2 - phi1
    dlambda = (pd.Series(lon2) - lon1).map(math.radians)
    a = (dphi / 2).map(math.sin) ** 2 + math.cos(phi1) * phi2.map(math.cos) * (
        (dlambda / 2).map(math.sin) ** 2
    )
    return 2 * EARTH_RADIUS_KM * a.map(math.sqrt).map(math.asin)


def fetch_ercot_solar_fleet() -> pd.DataFrame:
    """Every ERCOT solar generator with nameplate capacity, in-service month,
    and coordinates, from EIA's operating-generator-capacity route.

    One snapshot is enough for the whole history: each row carries its own
    `operating-year-month`, so capacity_online_by_year() can roll the fleet
    forward without a query per year. Cached, since this changes monthly at
    most.
    """
    cached = store.read_frame(source="penetration", key="ercot_solar_fleet", year=2026)
    if cached is not None:
        return cached

    api_key = os.environ.get("EIA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "EIA_API_KEY must be set (e.g. in a .env file) to fetch solar "
            "capacity -- see https://www.eia.gov/opendata/register.php"
        )

    params = {
        "api_key": api_key,
        "frequency": "monthly",
        "data[0]": "nameplate-capacity-mw",
        "data[1]": "operating-year-month",
        "data[2]": "latitude",
        "data[3]": "longitude",
        "data[4]": "county",
        "facets[balancing_authority_code][0]": "ERCO",
        "facets[technology][0]": "Solar Photovoltaic",
        "start": FLEET_SNAPSHOT_PERIOD,
        "end": FLEET_SNAPSHOT_PERIOD,
        "length": 5000,
    }
    response = requests.get(EIA_GENERATOR_CAPACITY_URL, params=params, timeout=120)
    response.raise_for_status()
    rows = response.json()["response"]["data"]
    if not rows:
        raise ValueError("EIA returned no ERCOT solar generators -- check the facets")

    fleet = pd.DataFrame(rows)
    fleet = fleet[
        [
            "plantid",
            "plantName",
            "generatorid",
            "nameplate-capacity-mw",
            "operating-year-month",
            "latitude",
            "longitude",
            "county",
        ]
    ].copy()
    fleet["nameplate-capacity-mw"] = pd.to_numeric(
        fleet["nameplate-capacity-mw"], errors="coerce"
    )
    fleet["latitude"] = pd.to_numeric(fleet["latitude"], errors="coerce")
    fleet["longitude"] = pd.to_numeric(fleet["longitude"], errors="coerce")
    fleet = fleet.dropna(subset=["nameplate-capacity-mw", "latitude", "longitude"])

    store.write_frame(fleet, source="penetration", key="ercot_solar_fleet", year=2026)
    return fleet


def capacity_online_by_year(
    fleet: pd.DataFrame,
    years: list[int],
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
) -> pd.Series:
    """Cumulative solar capacity (MW) in service at the end of each year.

    Pass lat/lon/radius_km to restrict to a project's neighbourhood -- the
    local build-out is what actually depresses a given node's midday prices.
    Omit them for the whole ERCOT footprint.

    A generator counts toward a year once its in-service month is on or
    before that December; nothing is retired here, so this is a build-out
    curve, not a true operating-fleet snapshot.
    """
    subset = fleet
    if radius_km is not None:
        if lat is None or lon is None:
            raise ValueError("radius_km requires both lat and lon")
        distance = _haversine_km(lat, lon, subset["latitude"], subset["longitude"])
        subset = subset[distance <= radius_km]

    online = pd.to_datetime(subset["operating-year-month"], errors="coerce")
    capacity = subset["nameplate-capacity-mw"]

    return pd.Series(
        {
            year: float(capacity[online <= pd.Timestamp(f"{year}-12-31")].sum())
            for year in years
        },
        name="solar_capacity_mw",
    )
