import pandas as pd
import pytest
from pydantic import ValidationError

from vppa import store
from vppa.ingest.generation import (
    _hourly_index_for_year,
    _read_resource_utc_offset,
    _resource_cache_dir,
    cache_key,
    fetch_pvwatts_generation,
)
from vppa.model import Contract


def test_tmy_index_is_8760_with_expected_dst_and_leap_day_artifacts():
    # 2024 is a leap year in America/Chicago (std offset -6). Localizing a
    # uniform naive local sequence to a real DST-observing zone can't
    # perfectly represent a real civil year: the naive sequence still has
    # length 8,760 (after dropping local Feb 29), but two of its consecutive
    # gaps are no longer a clean 1 hour -- one 0-hour gap where the
    # nonexistent spring-forward hour collided with the next real hour, and
    # one 2-hour gap where the doubled fall-back hour can't be represented at
    # all (TMY only ever has one naive row per hour label).
    index = _hourly_index_for_year(2024, std_offset_hours=-6)

    assert len(index) == 8760
    assert str(index.tz) == "UTC"
    assert index.is_monotonic_increasing

    gap_hours = (index[1:] - index[:-1]).total_seconds() / 3600
    assert (gap_hours == 1).sum() == 8756
    assert (gap_hours == 25).sum() == 1  # Feb 29 removed
    assert (gap_hours == 0).sum() == 1  # spring-forward collision (duplicate)
    assert (gap_hours == 2).sum() == 1  # fall-back hour TMY can't represent


def test_tmy_index_is_8760_on_non_leap_year():
    index = _hourly_index_for_year(2023, std_offset_hours=-6)

    assert len(index) == 8760
    assert str(index.tz) == "UTC"


def test_tmy_index_matches_standard_time_in_winter():
    # January isn't in DST, so this still matches the fixed-offset result:
    # local midnight Jan 1 in Chicago is 06:00 UTC the same day.
    index = _hourly_index_for_year(2023, std_offset_hours=-6)

    assert index[0] == pd.Timestamp("2023-01-01T06:00:00Z")


def test_tmy_index_shifts_by_dst_offset_in_summer():
    # July is in DST (Central = UTC-5, not the resource file's standard -6);
    # a fixed-offset conversion would put this one hour off from real market
    # time.
    index = _hourly_index_for_year(2023, std_offset_hours=-6)
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
    cached_index = _hourly_index_for_year(2024, std_offset_hours=-6)
    cached = pd.Series(1.0, index=cached_index[~cached_index.duplicated()], name="value")
    store.write_series(
        cached, source="generation", key=cache_key(example_contract), year=2024
    )

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


def test_fetch_rejects_unknown_weather_basis(example_contract):
    with pytest.raises(ValueError, match="weather must be"):
        fetch_pvwatts_generation(example_contract, 2024, weather="sunny")


def test_tmy_and_actual_use_separate_cache_namespaces(
    tmp_path, monkeypatch, example_contract
):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    index = _hourly_index_for_year(2024, std_offset_hours=-6)
    index = index[~index.duplicated()]
    store.write_series(
        pd.Series(1.0, index=index, name="value"),
        source="generation", key=cache_key(example_contract), year=2024,
    )

    # the TMY partition must not satisfy an actual-weather request: they are
    # different physical quantities and silently swapping them would make a
    # per-year P&L quietly wrong
    monkeypatch.delenv("NREL_API_KEY", raising=False)
    monkeypatch.delenv("NREL_API_EMAIL", raising=False)
    with pytest.raises(RuntimeError, match="NREL_API_KEY"):
        fetch_pvwatts_generation(example_contract, 2024, weather="actual")

    # ...while the TMY request is still served from cache
    assert len(fetch_pvwatts_generation(example_contract, 2024).series) == 8759


def _cached(contract, tmp_path, year=2024):
    index = _hourly_index_for_year(year, std_offset_hours=-6)
    index = index[~index.duplicated()]
    store.write_series(
        pd.Series(1.0, index=index, name="value"),
        source="generation", key=cache_key(contract), year=year,
    )


def test_cache_key_is_stable_for_an_unchanged_contract(example_contract):
    assert cache_key(example_contract) == cache_key(example_contract)
    assert cache_key(example_contract).startswith(example_contract.name + "__")


@pytest.mark.parametrize(
    "field, value",
    [
        ("tilt_deg", 35.0),
        ("azimuth_deg", 200.0),
        ("losses_pct", 10.0),
        ("dc_capacity_mw", 210.0),
        ("lat", 32.0),
        ("lon", -101.0),
        ("tracking", "single_axis_backtracked"),
    ],
)
def test_cache_key_changes_when_the_modelled_plant_changes(
    example_contract, field, value
):
    payload = example_contract.model_dump()
    payload["project"][field] = value
    changed = Contract.model_validate(payload)

    assert cache_key(changed) != cache_key(example_contract)


def test_cache_key_changes_with_contract_mw_because_it_sets_the_loading_ratio(
    example_contract,
):
    payload = example_contract.model_dump()
    payload["contract_mw"] = 120.0
    changed = Contract.model_validate(payload)

    assert changed.inverter_loading_ratio != example_contract.inverter_loading_ratio
    assert cache_key(changed) != cache_key(example_contract)


def test_cache_key_ignores_fields_that_do_not_reach_pvwatts(example_contract):
    # a re-struck deal on the same hardware should reuse the cached run --
    # the fingerprint is over the plant, not the paperwork
    payload = example_contract.model_dump()
    payload["strike_usd_mwh"] = 99.0
    payload["negative_price_floor"] = None
    unchanged = Contract.model_validate(payload)

    assert cache_key(unchanged) == cache_key(example_contract)


def test_retuned_project_is_not_served_the_previous_runs_generation(
    tmp_path, monkeypatch, example_contract
):
    # the bug this guards: the web editor can change tilt in one click, and
    # caching on the contract name alone returned the old series unchanged --
    # plausible numbers for a plant that was never modelled.
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.delenv("NREL_API_KEY", raising=False)
    monkeypatch.delenv("NREL_API_EMAIL", raising=False)
    _cached(example_contract, tmp_path)

    payload = example_contract.model_dump()
    payload["project"]["tilt_deg"] = 35.0
    retuned = Contract.model_validate(payload)

    with pytest.raises(RuntimeError, match="NREL_API_KEY"):
        fetch_pvwatts_generation(retuned, 2024)

    # ...and the original is still cached, so this is a miss, not a wipe
    assert len(fetch_pvwatts_generation(example_contract, 2024).series) == 8759


def test_resource_cache_follows_a_redirected_data_dir(tmp_path, monkeypatch):
    # bound at import, the NSRDB downloads landed in whatever directory the
    # process happened to start in
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)

    assert _resource_cache_dir() == tmp_path / "generation" / "_resource_cache"


def test_data_dir_is_not_relative_to_the_working_directory():
    assert store.DATA_DIR.is_absolute()


def test_tracking_defaults_to_fixed_rack_and_maps_to_pvwatts_codes(example_contract):
    assert example_contract.project.tracking == "fixed"
    assert example_contract.project.array_type == 0

    payload = example_contract.model_dump()
    for tracking, code in [("single_axis", 2), ("single_axis_backtracked", 3)]:
        payload["project"]["tracking"] = tracking
        assert Contract.model_validate(payload).project.array_type == code


def test_tracking_rejects_an_unknown_mounting(example_contract):
    payload = example_contract.model_dump()
    payload["project"]["tracking"] = "dual_axis"

    with pytest.raises(ValidationError):
        Contract.model_validate(payload)
