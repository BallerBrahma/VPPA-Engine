import pandas as pd
import pytest

from vppa import store
from vppa.ingest.prices import fetch_ercot_dam_prices, fetch_ercot_hub_dam_prices


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


class _DummyGsioClient:
    """Stands in for gridstatusio.GridStatusClient, recording its call args."""

    def __init__(self, frame, calls):
        self._frame = frame
        self._calls = calls

    def get_dataset(self, **kwargs):
        self._calls.append(kwargs)
        return self._frame


def _raw_gsio(utc_index, location="MCLNSLR_RN", spp=None):
    return pd.DataFrame(
        {
            "interval_start_utc": utc_index,
            "interval_end_utc": utc_index + pd.DateOffset(hours=1),
            "location": [location] * len(utc_index),
            "location_type": ["Resource Node"] * len(utc_index),
            "market": ["DAY_AHEAD_HOURLY"] * len(utc_index),
            "spp": spp or list(range(len(utc_index))),
        }
    )


def _patch_gsio(monkeypatch, frame, calls):
    monkeypatch.setenv("GRIDSTATUS_API_KEY", "test-key")
    monkeypatch.setattr(
        "gridstatusio.GridStatusClient",
        lambda api_key: _DummyGsioClient(frame, calls),
    )


def test_fetch_nodal_prices_filters_server_side_and_keeps_utc(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    utc_index = pd.date_range("2024-06-01", periods=4, freq="h", tz="UTC")
    calls = []
    _patch_gsio(monkeypatch, _raw_gsio(utc_index, spp=[10.0, -5.0, 20.0, 30.0]), calls)

    result = fetch_ercot_dam_prices("MCLNSLR_RN", 2024)

    assert result.settlement_point == "MCLNSLR_RN"
    assert str(result.series.index.tz) == "UTC"
    assert result.series.tolist() == [10.0, -5.0, 20.0, 30.0]
    # filtering must happen server-side -- pulling all ~1,100 nodes would
    # burn the row budget many times over
    assert calls[0]["filter_column"] == "location"
    assert calls[0]["filter_value"] == "MCLNSLR_RN"


def test_fetch_nodal_prices_caches_to_a_separate_source(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    utc_index = pd.date_range("2024-06-01", periods=3, freq="h", tz="UTC")
    calls = []
    _patch_gsio(monkeypatch, _raw_gsio(utc_index, spp=[1.0, 2.0, 3.0]), calls)

    fetch_ercot_dam_prices("MCLNSLR_RN", 2024)
    fetch_ercot_dam_prices("MCLNSLR_RN", 2024)

    # second call must be served from cache, not billed again
    assert len(calls) == 1
    assert store.read_series(source="prices_gsio", key="MCLNSLR_RN", year=2024) is not None
    # must not collide with the free-MIS cache namespace
    assert store.read_series(source="prices", key="MCLNSLR_RN", year=2024) is None


def test_fetch_nodal_prices_raises_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.delenv("GRIDSTATUS_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GRIDSTATUS_API_KEY"):
        fetch_ercot_dam_prices("MCLNSLR_RN", 2024)


def test_fetch_nodal_prices_raises_on_empty_result(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    calls = []
    _patch_gsio(monkeypatch, _raw_gsio(pd.DatetimeIndex([], tz="UTC")).iloc[0:0], calls)

    with pytest.raises(ValueError, match="energized"):
        fetch_ercot_dam_prices("NOTREAL_SLR", 2024)
