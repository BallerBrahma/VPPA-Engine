import pandas as pd
import pytest

from vppa.engine.metrics import (
    basis,
    breakeven_strike,
    capture_rate,
    cost_of_basis,
    negative_basis_hours,
)


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


def test_basis_is_node_minus_hub(basis_series):
    _, hub, node = basis_series

    result = basis(node, hub)

    assert result.tolist() == pytest.approx([0.0, -7.0, -6.0, 5.0])
    assert result.name == "basis"


def test_basis_rejects_misaligned_index(basis_series):
    _, hub, node = basis_series
    shifted_hub = hub.copy()
    shifted_hub.index = shifted_hub.index + pd.DateOffset(hours=1)

    with pytest.raises(ValueError, match="indexes do not match"):
        basis(node, shifted_hub)


def test_cost_of_basis_is_worse_than_the_simple_average(basis_series):
    generation, hub, node = basis_series
    basis_values = basis(node, hub)

    cost = cost_of_basis(basis_values, generation)

    # generation-weighted: (0*0 + 150*-7 + 140*-6 + 0*5) / 290 = -1890/290
    assert cost == pytest.approx(-1890 / 290)
    # the simple hourly mean is only -2.00 -- weighting by generation is the
    # whole point, since the one positive-basis hour has no output to earn it
    assert basis_values.mean() == pytest.approx(-2.0)
    assert cost < basis_values.mean()


def test_negative_basis_hours_counts_only_strictly_negative(basis_series):
    _, hub, node = basis_series

    assert negative_basis_hours(basis(node, hub)) == 2
