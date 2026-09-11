import pandas as pd
import pytest

from vppa.engine.dispatch import dispatch, storage_uplift
from vppa.model import StorageSpec


def _hours(n):
    return pd.date_range("2024-06-01", periods=n, freq="h", tz="UTC")


def _lossless(power=50.0, duration=2.0):
    return StorageSpec(
        power_mw=power, duration_hours=duration, round_trip_efficiency=1.0
    )


def test_battery_shifts_output_from_cheap_hour_to_dear_hour():
    idx = _hours(2)
    generation = pd.Series([100.0, 0.0], index=idx)
    price = pd.Series([-10.0, 90.0], index=idx)  # midday glut, evening peak

    result = dispatch(generation, price, _lossless(power=50.0, duration=2.0))

    # charge is capped by power (50), so 50 MWh moves out of the negative hour
    assert result["charge"].tolist() == pytest.approx([50.0, 0.0])
    assert result["discharge"].tolist() == pytest.approx([0.0, 50.0])
    assert result["delivered"].tolist() == pytest.approx([50.0, 50.0])


def test_battery_cannot_charge_from_the_grid():
    idx = _hours(2)
    generation = pd.Series([10.0, 0.0], index=idx)  # only 10 MWh available
    price = pd.Series([-50.0, 100.0], index=idx)

    result = dispatch(generation, price, _lossless(power=50.0, duration=4.0))

    # despite a 50 MW battery and a screaming spread, it can only take the
    # project's own 10 MWh -- no grid arbitrage leaks into the uplift
    assert result["charge"].tolist() == pytest.approx([10.0, 0.0])
    assert result["delivered"].tolist() == pytest.approx([0.0, 10.0])


def test_energy_capacity_caps_the_shift():
    idx = _hours(2)
    generation = pd.Series([100.0, 0.0], index=idx)
    price = pd.Series([0.0, 100.0], index=idx)

    # 50 MW power but only 1 hour of duration = 50 MWh usable, and here the
    # binding limit is energy, not power
    result = dispatch(generation, price, _lossless(power=80.0, duration=0.5))

    assert result["charge"].sum() == pytest.approx(40.0)
    assert result["soc"].max() <= 40.0 + 1e-6


def test_round_trip_losses_reduce_delivered_volume():
    idx = _hours(2)
    generation = pd.Series([100.0, 0.0], index=idx)
    price = pd.Series([0.0, 100.0], index=idx)
    storage = StorageSpec(power_mw=50.0, duration_hours=2.0, round_trip_efficiency=0.64)

    result = dispatch(generation, price, storage)

    # sqrt(0.64) = 0.8 each leg: 50 charged -> 40 stored -> 32 discharged
    assert result["charge"].sum() == pytest.approx(50.0)
    assert result["discharge"].sum() == pytest.approx(32.0)
    assert result["delivered"].sum() == pytest.approx(82.0)


def test_battery_idles_when_shifting_cannot_pay():
    idx = _hours(3)
    generation = pd.Series([100.0, 0.0, 0.0], index=idx)
    price = pd.Series([50.0, 10.0, 5.0], index=idx)  # best price is now

    result = dispatch(generation, price, _lossless())

    assert result["charge"].sum() == pytest.approx(0.0, abs=1e-6)
    assert result["delivered"].tolist() == pytest.approx([100.0, 0.0, 0.0])


def test_dispatch_rejects_misaligned_index():
    generation = pd.Series([1.0, 2.0], index=_hours(2))
    price = pd.Series([1.0, 2.0], index=_hours(2) + pd.DateOffset(hours=1))

    with pytest.raises(ValueError, match="indexes do not match"):
        dispatch(generation, price, _lossless())


def test_storage_uplift_raises_capture_rate():
    idx = _hours(4)
    generation = pd.Series([0.0, 120.0, 100.0, 0.0], index=idx)
    price = pd.Series([20.0, -5.0, 10.0, 80.0], index=idx)

    result = storage_uplift(generation, price, _lossless(power=60.0, duration=4.0))

    assert result["capture_rate_with_storage"] > result["capture_rate_base"]
    assert result["revenue_uplift_usd"] > 0
    # lossless battery moves energy without destroying it
    assert result["delivered_mwh"] == pytest.approx(result["generation_mwh"])
