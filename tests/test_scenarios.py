import pytest

from vppa.engine.scenarios import (
    Scenario,
    p90_factor,
    run_scenarios,
    standard_scenarios,
)


def test_p90_factor_is_1_2816_sigma_below_median():
    assert p90_factor(0.07) == pytest.approx(1 - 1.2816 * 0.07)
    # a project with no interannual variability has P90 == P50
    assert p90_factor(0.0) == pytest.approx(1.0)


def test_p90_factor_rejects_variability_that_would_flip_the_sign():
    with pytest.raises(ValueError, match="interannual_cv"):
        p90_factor(0.9)


def test_scenario_applies_price_factor_before_additive_basis(basic_series):
    generation, price = basic_series
    scenario = Scenario("x", price_factor=0.5, basis_shift_usd_mwh=-10.0)

    _, stressed = scenario.apply(generation, price)

    # 20 -> 20*0.5 - 10 = 0 ; -5 -> -5*0.5 - 10 = -12.5
    assert stressed.tolist() == pytest.approx([0.0, -12.5, -5.0, 12.5])


def test_scenario_basis_shift_can_push_price_negative(basic_series):
    generation, price = basic_series

    _, stressed = Scenario("x", basis_shift_usd_mwh=-25.0).apply(generation, price)

    # negative prices are a real outcome of a bad-basis year, never clamped
    assert stressed.min() < 0
    assert stressed.tolist() == pytest.approx([-5.0, -30.0, -15.0, 20.0])


def test_scenario_scales_generation(basic_series):
    generation, price = basic_series

    scaled, _ = Scenario("x", generation_factor=0.9).apply(generation, price)

    assert scaled.sum() == pytest.approx(290.0 * 0.9)


def test_run_scenarios_base_case_matches_unstressed_settlement(basic_series):
    generation, price = basic_series

    result = run_scenarios(generation, price, strike=34.50, floor=0.0)

    base = result.loc["base"]
    assert base["generation_mwh"] == pytest.approx(290.0)
    # same numbers the settlement fixture tests pin down
    assert base["cash_to_buyer_usd"] == pytest.approx(-5175.0 + -3430.0)
    assert base["breakeven_strike"] == pytest.approx(1400 / 290)


def test_run_scenarios_covers_the_designed_cases(basic_series):
    generation, price = basic_series

    result = run_scenarios(generation, price, strike=34.50, floor=0.0)

    assert list(result.index) == [
        "base",
        "p90_production",
        "price_collapse",
        "bad_basis_year",
        "combined_stress",
    ]
    # a dimmer year cuts volume but not the price the asset captures
    assert result.loc["p90_production", "generation_mwh"] < result.loc["base", "generation_mwh"]
    assert result.loc["p90_production", "breakeven_strike"] == pytest.approx(
        result.loc["base", "breakeven_strike"]
    )
    base_cash = result.loc["base", "cash_to_buyer_usd"]
    # price and basis stresses widen the buyer's loss
    assert result.loc["price_collapse", "cash_to_buyer_usd"] < base_cash
    assert result.loc["bad_basis_year", "cash_to_buyer_usd"] < base_cash
    # but a P90 year *helps* this buyer: the contract is underwater in every
    # lit hour, so less production means less volume to pay out on. P90 is a
    # downside case for the seller, not for a buyer in this position -- which
    # is exactly why scenarios are reported per counterparty, not as one
    # "bad case" number.
    assert result.loc["p90_production", "cash_to_buyer_usd"] > base_cash


def test_standard_scenarios_are_parameterised():
    scenarios = standard_scenarios(price_collapse=0.5, bad_basis_usd_mwh=20)
    by_name = {s.name: s for s in scenarios}

    assert by_name["price_collapse"].price_factor == pytest.approx(0.5)
    # sign is normalised, so passing a positive "bad basis" still hurts
    assert by_name["bad_basis_year"].basis_shift_usd_mwh == pytest.approx(-20.0)
