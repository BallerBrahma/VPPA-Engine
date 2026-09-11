import pandas as pd
import pytest

from vppa import store
from vppa.ingest.penetration import (
    _haversine_km,
    capacity_online_by_year,
    fetch_ercot_solar_fleet,
)


def _fleet():
    return pd.DataFrame(
        {
            "plantid": [1, 2, 3],
            "plantName": ["near_old", "near_new", "far_old"],
            "generatorid": ["a", "b", "c"],
            "nameplate-capacity-mw": [100.0, 250.0, 500.0],
            "operating-year-month": ["2019-06", "2024-03", "2019-01"],
            # Midland TX, ~50km away, and Houston (far)
            "latitude": [31.99, 32.40, 29.76],
            "longitude": [-102.08, -102.08, -95.37],
            "county": ["Midland", "Martin", "Harris"],
        }
    )


def test_haversine_matches_known_distance():
    # Midland to Houston, great-circle (not road) distance: ~425 mi / ~686 km
    km = _haversine_km(31.99, -102.08, pd.Series([29.76]), pd.Series([-95.37]))

    assert km.iloc[0] == pytest.approx(686, rel=0.02)


def test_capacity_accumulates_as_plants_come_online():
    result = capacity_online_by_year(_fleet(), years=[2023, 2024, 2025])

    # the 2024-03 plant only counts from 2024 onward
    assert result[2023] == pytest.approx(600.0)
    assert result[2024] == pytest.approx(850.0)
    assert result[2025] == pytest.approx(850.0)


def test_radius_filter_excludes_distant_plants():
    result = capacity_online_by_year(
        _fleet(), years=[2025], lat=31.99, lon=-102.08, radius_km=100
    )

    # the 500 MW Houston plant is far outside the radius
    assert result[2025] == pytest.approx(350.0)


def test_radius_requires_coordinates():
    with pytest.raises(ValueError, match="requires both lat and lon"):
        capacity_online_by_year(_fleet(), years=[2025], radius_km=100)


def test_fetch_returns_cached_fleet_without_touching_network(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.write_frame(_fleet(), source="penetration", key="ercot_solar_fleet", year=2026)

    def _boom(*args, **kwargs):
        raise AssertionError("should not hit EIA on a cache hit")

    monkeypatch.setattr("requests.get", _boom)

    assert len(fetch_ercot_solar_fleet()) == 3


def test_fetch_raises_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.delenv("EIA_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="EIA_API_KEY"):
        fetch_ercot_solar_fleet()
