import pandas as pd
import pytest

from vppa import store
from vppa.ingest.prices import fetch_ercot_hub_dam_prices


class _DummyErcot:
    def __init__(self, frame):
        self._frame = frame

    def get_dam_spp(self, year):
        return self._frame


def _raw_dam_spp(utc_index, hub="HB_WEST", spp=None):
    central_index = utc_index.tz_convert("US/Central")
    return pd.DataFrame(
        {
            "Interval Start": central_index,
            "Location": [hub] * len(utc_index),
            "SPP": spp or list(range(len(utc_index))),
        }
    )


def test_fetch_converts_central_to_utc(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    utc_index = pd.to_datetime(
        ["2024-06-01T05:00:00Z", "2024-06-01T06:00:00Z", "2024-06-01T07:00:00Z"]
    )
    raw = _raw_dam_spp(utc_index, spp=[10.0, 20.0, 30.0])
    monkeypatch.setattr("gridstatus.Ercot", lambda: _DummyErcot(raw))

    result = fetch_ercot_hub_dam_prices("HB_WEST", 2024)

    assert str(result.series.index.tz) == "UTC"
    assert list(result.series.index) == list(utc_index)
    assert result.series.tolist() == [10.0, 20.0, 30.0]


def test_fetch_dedupes_dst_fall_back_hour_correctly(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    # 2024-11-03 is ERCOT's fall-back date: 1 AM Central occurs twice in real
    # time (05:00Z and 06:00Z UTC both map to "1 AM"), but as genuine distinct
    # UTC instants there is no collision once converted back.
    utc_index = pd.to_datetime(
        [
            "2024-11-03T04:00:00Z",
            "2024-11-03T05:00:00Z",
            "2024-11-03T06:00:00Z",
            "2024-11-03T07:00:00Z",
        ]
    )
    raw = _raw_dam_spp(utc_index, spp=[10.0, 20.0, 30.0, 40.0])
    monkeypatch.setattr("gridstatus.Ercot", lambda: _DummyErcot(raw))

    result = fetch_ercot_hub_dam_prices("HB_WEST", 2024)

    assert not result.series.index.has_duplicates
    assert len(result.series) == 4
    assert result.series.tolist() == [10.0, 20.0, 30.0, 40.0]


def test_fetch_raises_on_unknown_hub(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    utc_index = pd.to_datetime(["2024-06-01T05:00:00Z"])
    raw = _raw_dam_spp(utc_index, hub="HB_NORTH")
    monkeypatch.setattr("gridstatus.Ercot", lambda: _DummyErcot(raw))

    with pytest.raises(ValueError, match="HB_WEST"):
        fetch_ercot_hub_dam_prices("HB_WEST", 2024)


def test_fetch_returns_cached_series_without_touching_network(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    index = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    cached = pd.Series([1.0, 2.0, 3.0], index=index, name="value")
    store.write_series(cached, source="prices", key="HB_WEST", year=2024)

    def _boom():
        raise AssertionError("should not construct Ercot() on a cache hit")

    monkeypatch.setattr("gridstatus.Ercot", _boom)

    result = fetch_ercot_hub_dam_prices("HB_WEST", 2024)

    assert result.settlement_point == "HB_WEST"
    assert len(result.series) == 3
