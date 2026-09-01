import pandas as pd
import pytest

from vppa.engine.settlement import settle

STRIKE = 34.50


def test_settle_with_negative_price_floor(basic_series):
    generation, price = basic_series

    result = settle(generation, price, strike=STRIKE, floor=0.0)

    assert list(result.columns) == ["index_price", "generation", "unit_diff", "cash_to_buyer"]
    # raw index_price is preserved unclipped, including the negative hour
    assert result["index_price"].tolist() == [20.00, -5.00, 10.00, 45.00]
    assert result["unit_diff"].tolist() == pytest.approx([-14.5, -34.5, -24.5, 10.5])
    assert result["cash_to_buyer"].tolist() == pytest.approx([0.0, -5175.0, -3430.0, 0.0])


def test_settle_without_floor_lets_negative_price_pass_through(basic_series):
    generation, price = basic_series

    result = settle(generation, price, strike=STRIKE, floor=None)

    # no floor -> the negative-price hour costs the buyer more, not less,
    # since the seller can claim (strike - index_price) uncapped
    assert result["unit_diff"].tolist() == pytest.approx([-14.5, -39.5, -24.5, 10.5])
    assert result["cash_to_buyer"].tolist() == pytest.approx([0.0, -5925.0, -3430.0, 0.0])


def test_settle_demonstrates_the_thesis(basic_series):
    """Solar generates when solar suppresses prices: the two highest-generation
    hours (negative and low price) are the two worst hours for the buyer, while
    the highest price of the day (evening peak) coincides with zero output."""
    generation, price = basic_series

    result = settle(generation, price, strike=STRIKE, floor=0.0)

    worst_hours = result["cash_to_buyer"].nsmallest(2).index
    assert set(worst_hours) == {
        pd.Timestamp("2024-06-01T12:00:00Z"),
        pd.Timestamp("2024-06-01T13:00:00Z"),
    }
    assert result.loc["2024-06-01T20:00:00Z", "generation"] == 0.0
    assert result["index_price"].idxmax() == pd.Timestamp("2024-06-01T20:00:00Z")


def test_settle_rejects_misaligned_index(basic_series):
    generation, price = basic_series
    shifted_price = price.copy()
    shifted_price.index = shifted_price.index + pd.DateOffset(hours=1)

    with pytest.raises(ValueError, match="index"):
        settle(generation, shifted_price, strike=STRIKE)
