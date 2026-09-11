"""gridstatus wrappers + Parquet caching for day-ahead / real-time LMPs."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from vppa import store
from vppa.model import PriceSeries

load_dotenv()

# gridstatus.io's hosted dataset covering every ERCOT settlement point --
# trading hubs, load zones, and resource nodes -- back through 2011.
GSIO_DAM_DATASET = "ercot_spp_day_ahead_hourly"


def fetch_ercot_hub_dam_prices(hub: str, year: int) -> PriceSeries:
    """Day-ahead hourly settlement point price ($/MWh) at an ERCOT trading hub
    for one calendar year.

    Source data is tz-aware US/Central -- a real, DST-observing zone, unlike
    the synthetic TMY calendar used for generation. Converting via
    tz_convert("UTC") (rather than re-labeling the raw local hours) is what
    keeps the DST fall-back hour from silently colliding into a duplicate
    UTC timestamp; PriceSeries validation rejects a duplicate on the way in
    as a second line of defense.

    Caches the result so repeat runs for the same hub/year don't re-hit
    ERCOT's site.
    """
    cached = store.read_series(source="prices", key=hub, year=year)
    if cached is not None:
        return PriceSeries(settlement_point=hub, series=cached)

    from gridstatus import Ercot

    raw = Ercot().get_dam_spp(year)
    at_hub = raw[raw["Location"] == hub]
    if at_hub.empty:
        raise ValueError(f"no DAM SPP rows for hub {hub!r} in {year} -- check the hub name")

    series = at_hub.set_index("Interval Start")["SPP"].sort_index()
    series.index = series.index.tz_convert("UTC")
    series.index.name = None
    series.name = "index_price"

    store.write_series(series, source="prices", key=hub, year=year)
    return PriceSeries(settlement_point=hub, series=series)


def fetch_ercot_dam_prices(location: str, year: int) -> PriceSeries:
    """Day-ahead hourly SPP ($/MWh) at *any* ERCOT settlement point -- trading
    hub, load zone, or resource node -- for one calendar year, via the
    gridstatus.io hosted API.

    Resource-node history is why this exists: ERCOT's free MIS keeps only a
    ~31-day rolling window of nodal prices, so basis work over multiple years
    can't be done from the archive that fetch_ercot_hub_dam_prices() uses.

    For a basis calculation, pull *both* legs (node and hub) through this
    function rather than mixing sources -- two feeds of nominally the same
    hub can differ in price corrections and republication timing.

    Results are cached per (location, year); the hosted API bills by row and
    a year is 8,760 of them, so a cache hit is worth real budget.
    """
    cached = store.read_series(source="prices_gsio", key=location, year=year)
    if cached is not None:
        return PriceSeries(settlement_point=location, series=cached)

    api_key = os.environ.get("GRIDSTATUS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GRIDSTATUS_API_KEY must be set (e.g. in a .env file) to fetch "
            "nodal prices -- see https://www.gridstatus.io/"
        )

    from gridstatusio import GridStatusClient

    raw = GridStatusClient(api_key=api_key).get_dataset(
        dataset=GSIO_DAM_DATASET,
        start=f"{year}-01-01",
        end=f"{year + 1}-01-01",
        filter_column="location",
        filter_value=location,
        verbose=False,
    )
    if raw.empty:
        raise ValueError(
            f"no DAM SPP rows for location {location!r} in {year} -- check the "
            "settlement point name, or whether it was energized that year"
        )

    # interval_start_utc already arrives tz-aware UTC, so no DST conversion
    # is needed here (unlike the MIS archive, which reports US/Central).
    series = raw.set_index("interval_start_utc")["spp"].sort_index()
    series = series[~series.index.duplicated()]
    series.index.name = None
    series.name = "index_price"

    store.write_series(series, source="prices_gsio", key=location, year=year)
    return PriceSeries(settlement_point=location, series=series)
