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
    # the other 50 MWh is curtailed rather than exported at -$10: the battery
    # takes what it can hold and the plant declines to sell the rest at a loss
    assert result["curtailed"].tolist() == pytest.approx([50.0, 0.0])
    assert result["delivered"].tolist() == pytest.approx([0.0, 50.0])


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
    # a lossless battery destroys no energy, but curtailment does, so the
    # accounting identity is generation = delivered + curtailed + round-trip loss
    assert result["round_trip_loss_mwh"] == pytest.approx(0.0, abs=1e-6)
    assert result["delivered_mwh"] + result["curtailed_mwh"] == pytest.approx(
        result["generation_mwh"]
    )


def _with_cycling(cost, power=50.0, duration=2.0, efficiency=1.0):
    return StorageSpec(
        power_mw=power,
        duration_hours=duration,
        round_trip_efficiency=efficiency,
        cycling_cost_usd_mwh=cost,
    )


def test_one_inverter_forbids_charging_and_discharging_at_once():
    """Without this the LP does both in the same hour whenever it is free --
    revenue is unchanged, but the invented throughput inflates cycle counts."""
    idx = _hours(3)
    generation = pd.Series([100.0, 0.0, 0.0], index=idx)
    price = pd.Series([50.0, 10.0, 5.0], index=idx)

    result = dispatch(generation, price, _lossless())

    both = result["charge"] + result["discharge"]
    assert (both <= _lossless().power_mw + 1e-6).all()
    # best price is the first hour, so the right answer is to do nothing
    assert result["charge"].sum() == pytest.approx(0.0, abs=1e-6)


def test_cycling_cost_stops_the_battery_chasing_a_spread_it_cannot_cover():
    idx = _hours(2)
    generation = pd.Series([100.0, 0.0], index=idx)
    price = pd.Series([10.0, 14.0], index=idx)  # a $4 spread

    free = dispatch(generation, price, _with_cycling(0.0))
    priced = dispatch(generation, price, _with_cycling(6.0))

    assert free["charge"].sum() > 0  # worth it when wear is free
    assert priced["charge"].sum() == pytest.approx(0.0, abs=1e-6)


def test_cycling_cost_is_reported_against_throughput():
    idx = _hours(2)
    generation = pd.Series([100.0, 0.0], index=idx)
    price = pd.Series([0.0, 90.0], index=idx)

    result = storage_uplift(generation, price, _with_cycling(3.0))

    assert result["cycling_cost_usd"] == pytest.approx(50.0 * 3.0)


def test_curtailment_threshold_lets_a_ptc_project_export_below_zero():
    idx = _hours(1)
    generation = pd.Series([100.0], index=idx)
    price = pd.Series([-20.0], index=idx)
    tiny = StorageSpec(power_mw=0.001, duration_hours=1.0, round_trip_efficiency=1.0)

    merchant = dispatch(generation, price, tiny)
    with_ptc = dispatch(generation, price, tiny, curtail_below_usd_mwh=-27.5)

    # a merchant plant walks away at $0; one earning the production tax credit
    # keeps generating, which is a large part of why ERCOT prices go negative.
    # The battery is deliberately negligible, so everything it cannot absorb is
    # the curtailment decision.
    assert merchant["curtailed"].iloc[0] == pytest.approx(
        100.0 - merchant["charge"].iloc[0]
    )
    assert with_ptc["curtailed"].iloc[0] == pytest.approx(0.0, abs=1e-6)


def test_daily_foresight_cannot_move_energy_between_days():
    idx = pd.date_range("2024-06-01", periods=48, freq="h", tz="UTC")
    generation = pd.Series(0.0, index=idx)
    generation.iloc[0] = 100.0  # all output on day one
    price = pd.Series(10.0, index=idx)
    price.iloc[40] = 500.0  # the best hour is on day two

    annual = dispatch(generation, price, _lossless(power=50.0, duration=4.0))
    daily = dispatch(
        generation, price, _lossless(power=50.0, duration=4.0), foresight="daily"
    )

    # knowing the whole year, the battery holds energy overnight for the spike
    assert annual["discharge"].iloc[40] > 0
    # a day-ahead bidder cannot: day one is solved without ever seeing day two
    assert daily["discharge"].iloc[40] == pytest.approx(0.0, abs=1e-6)


def test_foresight_premium_is_never_negative():
    """The annual LP has strictly more freedom than the daily one, so it cannot
    do worse -- if this ever goes negative the daily decomposition is broken."""
    from vppa.engine.dispatch import foresight_premium

    idx = pd.date_range("2024-06-01", periods=72, freq="h", tz="UTC")
    generation = pd.Series(
        [max(0.0, 60.0 - abs(h % 24 - 13) * 9) for h in range(72)], index=idx
    )
    price = pd.Series([25.0 + (h % 24 - 12) * 4 for h in range(72)], index=idx)

    premium = foresight_premium(generation, price, _lossless(power=30.0, duration=4.0))

    assert premium["foresight_premium_usd"] >= -1e-6


def test_dispatch_rejects_an_unknown_foresight_mode():
    idx = _hours(2)
    generation = pd.Series([10.0, 0.0], index=idx)
    price = pd.Series([1.0, 2.0], index=idx)

    with pytest.raises(ValueError, match="foresight must be"):
        dispatch(generation, price, _lossless(), foresight="clairvoyant")


def test_daily_foresight_cuts_days_in_market_time_not_utc():
    """ERCOT's evening peak is the next UTC day.

    Splitting on UTC days severed the charge-then-discharge cycle: a West Texas
    battery puts 62% of its discharge into UTC hours 00-03, which is 18:00-21:00
    Central the same afternoon. Cutting there made the daily LP look 65% worse
    than annual, when the real gap is under 10%.
    """
    # 09:00 Central (15:00 UTC) midday glut, 19:00 Central (01:00 UTC next day) peak
    idx = pd.date_range("2024-06-01 12:00", periods=24, freq="h", tz="UTC")
    generation = pd.Series(0.0, index=idx)
    generation.iloc[3] = 100.0  # 15:00 UTC = 10:00 Central
    price = pd.Series(20.0, index=idx)
    price.iloc[3] = 1.0
    price.iloc[13] = 200.0  # 01:00 UTC next day = 20:00 Central, same operating day

    daily = dispatch(
        generation, price, _lossless(power=50.0, duration=4.0), foresight="daily"
    )

    # both hours are the same Central operating day, so the battery must be
    # allowed to carry energy between them
    assert daily["charge"].iloc[3] > 0
    assert daily["discharge"].iloc[13] == pytest.approx(daily["charge"].iloc[3])

    # cutting on UTC days instead puts them in different blocks and the trade
    # disappears entirely
    utc_split = dispatch(
        generation,
        price,
        _lossless(power=50.0, duration=4.0),
        foresight="daily",
        market_timezone="UTC",
    )
    assert utc_split["discharge"].iloc[13] == pytest.approx(0.0, abs=1e-6)


def test_the_battery_must_be_offered_energy_the_plant_would_have_spilled():
    """Curtailing before dispatch answers a different, worse question.

    Absorbing oversupplied hours is most of what storage is for. Handing the LP
    a series with those hours already zeroed hides the value it exists to
    measure -- and quietly disagrees with a caller that passes gross output.
    """
    from vppa.engine.curtailment import economic_curtailment

    idx = _hours(3)
    generation = pd.Series([100.0, 0.0, 0.0], index=idx)
    price = pd.Series([-5.0, 10.0, 90.0], index=idx)
    spec = _lossless(power=50.0, duration=2.0)

    gross = dispatch(generation, price, spec)
    delivered = economic_curtailment(generation, price)["delivered"]
    pre_curtailed = dispatch(delivered, price, spec)

    # offered the real output, the battery stores 50 MWh and sells it at $90
    assert gross["charge"].iloc[0] == pytest.approx(50.0)
    assert gross["discharge"].iloc[2] == pytest.approx(50.0)
    assert float((gross["delivered"] * price).sum()) == pytest.approx(4500.0)

    # offered a series already zeroed, it has nothing to work with
    assert pre_curtailed["charge"].sum() == pytest.approx(0.0, abs=1e-6)
    assert float((pre_curtailed["delivered"] * price).sum()) == pytest.approx(0.0)
