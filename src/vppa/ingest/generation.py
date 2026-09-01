"""PySAM PVWatts runner: contract project config -> hourly AC generation."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from vppa import store
from vppa.model import Contract, GenerationProfile

load_dotenv()

RESOURCE_CACHE_DIR = Path("data") / "generation" / "_resource_cache"

# NSRDB reports weather in fixed standard time (no DST -- solar position
# doesn't observe clock changes), but the ISO markets we'll join this against
# settle on prevailing local time, which does. Mapping the standard-time
# offset to the region's actual DST-observing zone means "hour 14" lines up
# with the same real market hour year-round, not just in winter. Limited to
# the CONUS zones the design doc's target ISOs actually operate in.
_STANDARD_OFFSET_TO_PREVAILING_ZONE = {
    -5: "America/New_York",
    -6: "America/Chicago",
    -7: "America/Denver",
    -8: "America/Los_Angeles",
}


def _read_resource_utc_offset(resource_file: str) -> int:
    """NSRDB resource CSVs declare their fixed standard-time offset as whole
    hours in the header's 'Time Zone' column. PVWatts' hourly output array is
    ordered in that same local standard time, not UTC.
    """
    header = pd.read_csv(resource_file, nrows=1)
    return int(header["Time Zone"].iloc[0])


def _tmy_index_for_year(year: int, std_offset_hours: int) -> pd.DatetimeIndex:
    """UTC hourly index to stamp a TMY output onto, positionally aligned with
    PVWatts' raw 8,760-value output array (see fetch_pvwatts_generation for
    how the one DST collision this produces gets resolved).

    A TMY resource is a synthetic composite year: exactly 8,760 hours, no
    Feb 29, and no notion of daylight saving. Feb 29 is dropped from the
    target calendar in local time; the remaining naive hours are localized to
    the region's real prevailing (DST-observing) timezone rather than the
    resource file's fixed offset, so generation lines up with real market
    hours across the whole year, not just in winter.

    Localizing a uniform naive sequence into a DST-observing zone hits one
    genuine structural mismatch: the naive spring-forward hour (e.g. 2 AM)
    doesn't exist locally that day, so it's shifted forward -- which lands on
    the same UTC instant as the following naive hour, producing one
    duplicate timestamp in the length-8,760 result. TMY has no way to
    represent a real civil year's flip side (the doubled fall-back hour), so
    the two effects don't cancel out; resolving the duplicate is left to the
    caller, which has the matching values to drop alongside it.
    """
    local_index = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    local_index = local_index[~((local_index.month == 2) & (local_index.day == 29))]
    try:
        zone = _STANDARD_OFFSET_TO_PREVAILING_ZONE[std_offset_hours]
    except KeyError:
        raise ValueError(
            f"no known prevailing timezone for standard-time offset {std_offset_hours} "
            "-- add it to _STANDARD_OFFSET_TO_PREVAILING_ZONE"
        ) from None
    localized = local_index.tz_localize(zone, ambiguous=True, nonexistent="shift_forward")
    return localized.tz_convert("UTC")


def fetch_pvwatts_generation(contract: Contract, year: int) -> GenerationProfile:
    """Run PVWatts against TMY weather for `contract.project`, stamped onto
    `year`'s UTC calendar.

    Phase 1 uses TMY (typical, not actual, weather) -- see design doc section
    2. Results are "typical production against actual [year] prices," not
    that year's real weather; phase 2 should switch to actual-year NSRDB data
    before calling any single year's P&L finished.

    Caches the NSRDB resource file and the resulting generation series so
    repeat runs for the same contract/year don't re-hit the network.
    """
    cached = store.read_series(source="generation", key=contract.name, year=year)
    if cached is not None:
        return GenerationProfile(project_name=contract.name, series=cached)

    api_key = os.environ.get("NREL_API_KEY")
    api_email = os.environ.get("NREL_API_EMAIL")
    if not api_key or not api_email:
        raise RuntimeError(
            "NREL_API_KEY and NREL_API_EMAIL must be set (e.g. in a .env file) "
            "to fetch TMY weather from NSRDB -- see https://developer.nrel.gov/signup/"
        )

    from PySAM import Pvwattsv8, ResourceTools

    RESOURCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fetcher = ResourceTools.FetchResourceFiles(
        tech="pv",
        nrel_api_key=api_key,
        nrel_api_email=api_email,
        resource_dir=str(RESOURCE_CACHE_DIR),
        verbose=False,
    )
    fetcher.fetch([(contract.project.lon, contract.project.lat)])
    resource_file = fetcher.resource_file_paths[0]
    utc_offset_hours = _read_resource_utc_offset(resource_file)

    model = Pvwattsv8.default("PVWattsNone")
    model.SolarResource.solar_resource_file = resource_file
    model.SystemDesign.system_capacity = contract.project.dc_capacity_mw * 1000  # kW
    # ILR clips midday peaks and flattens shoulders -- must be set explicitly,
    # PVWatts otherwise defaults to 1.2 regardless of the project's real ratio.
    model.SystemDesign.dc_ac_ratio = contract.inverter_loading_ratio
    model.SystemDesign.tilt = contract.project.tilt_deg
    model.SystemDesign.azimuth = contract.project.azimuth_deg
    model.SystemDesign.losses = contract.project.losses_pct
    model.SystemDesign.array_type = 0  # fixed open rack; revisit if a project uses tracking
    model.execute()

    ac_watts = pd.Series(model.Outputs.ac, dtype=float)
    if len(ac_watts) != 8760:
        raise ValueError(f"expected 8,760 hourly TMY values from PVWatts, got {len(ac_watts)}")

    # PVWatts' Outputs.ac is instantaneous AC power in watts; over a 1-hour
    # interval that's numerically equal to Wh, so /1e6 converts straight to MWh.
    generation_mwh = ac_watts / 1_000_000.0
    generation_mwh.index = _tmy_index_for_year(year, utc_offset_hours)
    generation_mwh.name = "generation_mwh"

    # collapse the single spring-forward collision documented in
    # _tmy_index_for_year -- both rows are TMY's typical value for that
    # hour anyway, so keeping the first is not a meaningful data loss.
    duplicate_hours = generation_mwh.index.duplicated(keep="first")
    if duplicate_hours.any():
        generation_mwh = generation_mwh[~duplicate_hours]

    store.write_series(generation_mwh, source="generation", key=contract.name, year=year)

    return GenerationProfile(project_name=contract.name, series=generation_mwh)
