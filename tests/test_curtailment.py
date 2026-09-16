import pandas as pd
import pytest

from vppa.engine.curtailment import curtailment_summary, economic_curtailment
from vppa.engine.settlement import settle


def _hours(n):
    return pd.date_range("2024-06-01", periods=n, freq="h", tz="UTC")


def test_negative_price_hours_are_curtailed_entirely():
    idx = _hours(4)
    generation = pd.Series([10.0, 40.0, 60.0, 5.0], index=idx)
    price = pd.Series([25.0, -8.0, -0.01, 40.0], index=idx)

    result = economic_curtailment(generation, price)

    assert result["delivered"].tolist() == [10.0, 0.0, 0.0, 5.0]
    assert result["curtailed"].tolist() == [0.0, 40.0, 60.0, 0.0]


def test_a_zero_price_hour_is_not_curtailed():
    # exactly zero is break-even, not a loss: curtailing it changes nothing,
    # and treating it as a loss would overstate curtailment in a market that
    # settles at exactly $0 more often than you would expect
    idx = _hours(1)
    result = economic_curtailment(
        pd.Series([50.0], index=idx), pd.Series([0.0], index=idx)
    )

    assert result["curtailed"].iloc[0] == 0.0


def test_a_production_incentive_keeps_the_plant_running_below_zero():
    idx = _hours(3)
    generation = pd.Series([50.0, 50.0, 50.0], index=idx)
    price = pd.Series([-10.0, -27.0, -30.0], index=idx)

    result = economic_curtailment(generation, price, curtail_below_usd_mwh=-27.5)

    # generates down to -27.50 and stops below it
    assert result["delivered"].tolist() == [50.0, 50.0, 0.0]


def test_curtailment_improves_the_buyers_position():
    """Counterintuitive but central: curtailment removes only hours the buyer
    was paying into, so it cuts volume and losses at the same time."""
    idx = _hours(3)
    generation = pd.Series([50.0, 50.0, 50.0], index=idx)
    price = pd.Series([60.0, -20.0, 45.0], index=idx)
    strike = 35.0

    uncurtailed = settle(generation, price, strike=strike)
    delivered = economic_curtailment(generation, price)["delivered"]
    curtailed = settle(delivered, price, strike=strike)

    assert curtailed["cash_to_buyer"].sum() > uncurtailed["cash_to_buyer"].sum()
    assert delivered.sum() < generation.sum()


def test_summary_reports_share_hours_and_revenue_saved():
    idx = _hours(4)
    generation = pd.Series([100.0, 100.0, 100.0, 100.0], index=idx)
    price = pd.Series([50.0, -10.0, -5.0, 50.0], index=idx)

    summary = curtailment_summary(economic_curtailment(generation, price), price)

    assert summary["curtailed_mwh"] == pytest.approx(200.0)
    assert summary["curtailed_share"] == pytest.approx(0.5)
    assert summary["curtailed_hours"] == 2
    # avoided selling 100 MWh at -$10 and 100 at -$5
    assert summary["revenue_saved_usd"] == pytest.approx(1500.0)


def test_curtailment_rejects_misaligned_inputs():
    generation = pd.Series([1.0], index=_hours(1))
    price = pd.Series([1.0, 2.0], index=_hours(2))

    with pytest.raises(ValueError, match="indexes do not match"):
        economic_curtailment(generation, price)


def test_an_all_curtailed_year_reports_a_full_share_without_dividing_by_zero():
    idx = _hours(2)
    summary = curtailment_summary(
        economic_curtailment(
            pd.Series([0.0, 0.0], index=idx), pd.Series([-5.0, -5.0], index=idx)
        ),
        pd.Series([-5.0, -5.0], index=idx),
    )

    assert summary["curtailed_share"] == 0.0
