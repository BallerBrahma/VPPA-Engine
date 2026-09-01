import pytest

from vppa.engine.metrics import breakeven_strike, capture_rate


def test_capture_rate_below_one_when_generation_coincides_with_low_prices(basic_series):
    generation, price = basic_series

    rate = capture_rate(generation, price)

    # generation-weighted price: (0*20 + 150*-5 + 140*10 + 0*45) / 290 = 650/290
    # time-weighted price: (20 - 5 + 10 + 45) / 4 = 17.5
    assert rate == pytest.approx((650 / 290) / 17.5)
    assert rate < 1.0


def test_breakeven_strike_with_floor_ignores_negative_hour(basic_series):
    generation, price = basic_series

    strike = breakeven_strike(generation, price, floor=0.0)

    # effective price floors the -5.00 hour to 0: (0*20 + 150*0 + 140*10 + 0*45) / 290
    assert strike == pytest.approx(1400 / 290)


def test_breakeven_strike_without_floor_matches_capture_rates_numerator(basic_series):
    generation, price = basic_series

    strike = breakeven_strike(generation, price, floor=None)

    # with no floor, breakeven strike is exactly the generation-weighted average
    # price used as capture_rate's numerator -- the two metrics share that core
    assert strike == pytest.approx(650 / 290)


def test_breakeven_strike_raises_on_zero_generation(basic_series):
    generation, price = basic_series
    zero_generation = generation * 0

    with pytest.raises(ValueError, match="zero total generation"):
        breakeven_strike(zero_generation, price)
