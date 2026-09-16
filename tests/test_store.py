import pandas as pd
import pytest

from vppa import store


def test_write_then_read_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    index = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    series = pd.Series([1.0, 2.0, 3.0], index=index, name="anything")

    store.write_series(series, source="prices", key="HB_WEST", year=2024)
    result = store.read_series(source="prices", key="HB_WEST", year=2024)

    # Parquet round-trips the index values but not the DatetimeIndex's freq metadata
    pd.testing.assert_series_equal(result, series.rename("value"), check_freq=False)


def test_read_missing_partition_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)

    result = store.read_series(source="prices", key="nowhere", year=1999)

    assert result is None


def test_write_refuses_to_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    index = pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC")
    series = pd.Series([1.0, 2.0], index=index)

    store.write_series(series, source="generation", key="proj", year=2024)

    with pytest.raises(FileExistsError, match="never mutated"):
        store.write_series(series, source="generation", key="proj", year=2024)


@pytest.mark.parametrize(
    "key",
    ["../escape", "../../../../tmp/pwned", "a/b", "a\\b", ".", "..", "", ".hidden"],
)
def test_cache_path_refuses_a_key_that_is_not_a_single_directory_name(key):
    # a contract name, hub and node all reach this from a posted request body
    with pytest.raises(ValueError):
        store.cache_path("generation", key, 2025)


def test_cache_path_stays_inside_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)

    path = store.cache_path("generation", "lamesa_solar_west__abc123", 2025)

    assert path.resolve().is_relative_to(tmp_path.resolve())


def test_write_series_refuses_an_escaping_key(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    index = pd.date_range("2025-01-01", periods=3, freq="h", tz="UTC")

    with pytest.raises(ValueError):
        store.write_series(
            pd.Series(1.0, index=index), source="generation", key="../out", year=2025
        )

    assert list(tmp_path.parent.glob("out")) == []
