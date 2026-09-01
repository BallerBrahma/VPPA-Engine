import pandas as pd
import pytest

from vppa.engine.settlement import settle
from vppa.report.statement import monthly_statement


def test_monthly_statement_single_month(basic_series):
    generation, price = basic_series
    settled = settle(generation, price, strike=34.50, floor=0.0)

    statement = monthly_statement(settled)

    assert len(statement) == 1
    row = statement.iloc[0]
    assert row["generation_mwh"] == pytest.approx(290.0)
    assert row["cash_to_buyer_usd"] == pytest.approx(-5175.0 + -3430.0)
    assert row["avg_market_price_usd_mwh"] == pytest.approx(17.5)
    # generation-weighted realized price, same math as capture_rate's numerator
    assert row["realized_price_usd_mwh"] == pytest.approx(650 / 290)


def test_monthly_statement_splits_across_months():
    index = pd.date_range("2024-01-15", periods=3, freq="MS", tz="UTC")
    generation = pd.Series([100.0, 200.0, 0.0], index=index)
    price = pd.Series([10.0, 20.0, 30.0], index=index)
    settled = settle(generation, price, strike=15.0, floor=None)

    statement = monthly_statement(settled)

    assert len(statement) == 3
    assert statement["generation_mwh"].tolist() == [100.0, 200.0, 0.0]
    # zero-generation month has an undefined (NaN) realized price, not a
    # divide-by-zero crash or a silently wrong zero
    assert statement["realized_price_usd_mwh"].isna().tolist() == [False, False, True]
