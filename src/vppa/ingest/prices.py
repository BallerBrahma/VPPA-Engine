"""gridstatus wrappers + Parquet caching for day-ahead / real-time LMPs."""

from __future__ import annotations

from vppa import store
from vppa.model import PriceSeries


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
