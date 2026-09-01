import pandas as pd
import pytest

from vppa import store
from vppa.ingest.generation import (
    _read_resource_utc_offset,
    _tmy_index_for_year,
    fetch_pvwatts_generation,
)


def test_tmy_index_is_8760_with_expected_dst_and_leap_day_artifacts():
    # 2024 is a leap year in America/Chicago (std offset -6). Localizing a
    # uniform naive local sequence to a real DST-observing zone can't
    # perfectly represent a real civil year: the naive sequence still has
    # length 8,760 (after dropping local Feb 29), but two of its consecutive
    # gaps are no longer a clean 1 hour -- one 0-hour gap where the
    # nonexistent spring-forward hour collided with the next real hour, and
    # one 2-hour gap where the doubled fall-back hour can't be represented at
    # all (TMY only ever has one naive row per hour label).
    index = _tmy_index_for_year(2024, std_offset_hours=-6)

    assert len(index) == 8760
    assert str(index.tz) == "UTC"
    assert index.is_monotonic_increasing

    gap_hours = (index[1:] - index[:-1]).total_seconds() / 3600
    assert (gap_hours == 1).sum() == 8756
    assert (gap_hours == 25).sum() == 1  # Feb 29 removed
    assert (gap_hours == 0).sum() == 1  # spring-forward collision (duplicate)
    assert (gap_hours == 2).sum() == 1  # fall-back hour TMY can't represent


def test_tmy_index_is_8760_on_non_leap_year():
    index = _tmy_index_for_year(2023, std_offset_hours=-6)

    assert len(index) == 8760
    assert str(index.tz) == "UTC"


def test_tmy_index_matches_standard_time_in_winter():
    # January isn't in DST, so this still matches the fixed-offset result:
    # local midnight Jan 1 in Chicago is 06:00 UTC the same day.
    index = _tmy_index_for_year(2023, std_offset_hours=-6)

    assert index[0] == pd.Timestamp("2023-01-01T06:00:00Z")


def test_tmy_index_shifts_by_dst_offset_in_summer():
    # July is in DST (Central = UTC-5, not the resource file's standard -6);
    # a fixed-offset conversion would put this one hour off from real market
    # time.
    index = _tmy_index_for_year(2023, std_offset_hours=-6)
    july_first_midnight = index[index.tz_convert("America/Chicago").hour == 0]
    july_first_midnight = july_first_midnight[
        (july_first_midnight.month == 7) & (july_first_midnight.day == 1)
    ]

    assert july_first_midnight[0] == pd.Timestamp("2023-07-01T05:00:00Z")


def test_read_resource_utc_offset(tmp_path):
    resource_file = tmp_path / "resource.csv"
    resource_file.write_text(
        "Source,Time Zone,Other\nNSRDB,-6,x\nYear,Month,Day,Hour,Minute\n2023,1,1,0,0\n"
    )

    assert _read_resource_utc_offset(str(resource_file)) == -6


def test_fetch_returns_cached_series_without_touching_network(
    tmp_path, monkeypatch, example_contract
):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    cached_index = _tmy_index_for_year(2024, std_offset_hours=-6)
    cached = pd.Series(1.0, index=cached_index[~cached_index.duplicated()], name="value")
    store.write_series(cached, source="generation", key=example_contract.name, year=2024)

    profile = fetch_pvwatts_generation(example_contract, 2024)

    assert profile.project_name == example_contract.name
    assert len(profile.series) == 8759


def test_fetch_raises_clear_error_without_api_credentials(
    tmp_path, monkeypatch, example_contract
):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.delenv("NREL_API_KEY", raising=False)
    monkeypatch.delenv("NREL_API_EMAIL", raising=False)

    with pytest.raises(RuntimeError, match="NREL_API_KEY"):
        fetch_pvwatts_generation(example_contract, 2024)
