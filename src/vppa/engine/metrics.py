"""capture_rate(), basis(), breakeven_strike() — transformations of settle()'s output."""

import pandas as pd


def _generation_weighted_average(values: pd.Series, generation_mwh: pd.Series) -> float:
    """sum(values * generation) / sum(generation)."""
    total_generation = generation_mwh.sum()
    if total_generation == 0:
        raise ValueError("cannot compute a generation-weighted average with zero total generation")
    return (values * generation_mwh).sum() / total_generation


def capture_rate(generation_mwh: pd.Series, index_price: pd.Series) -> float:
    """Ratio of what the asset actually earned per MWh to what a flat, always-on
    generator would have earned over the same hours.

    This ratio is the thesis, quantified: solar generates when solar suppresses
    prices, so the generation-weighted price it captures falls below the simple
    time-weighted average, and the gap widens as regional solar penetration grows.
    """
    realized_price = _generation_weighted_average(index_price, generation_mwh)
    average_market_price = index_price.mean()
    return realized_price / average_market_price


def breakeven_strike(
    generation_mwh: pd.Series,
    index_price: pd.Series,
    floor: float | None = None,
) -> float:
    """The strike at which this contract, given the asset's actual hourly
    production, would net to zero cash flow over the period.

    Mirrors settle()'s floor handling: cash_to_buyer = (effective_price - strike)
    * generation is linear in strike, so the break-even point is exactly the
    generation-weighted average of the effective (floor-adjusted) price.
    """
    effective_price = index_price if floor is None else index_price.clip(lower=floor)
    return _generation_weighted_average(effective_price, generation_mwh)
