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


def basis(node_price: pd.Series, hub_price: pd.Series) -> pd.Series:
    """Hourly locational basis in $/MWh: node price minus hub price.

    A hub-settled VPPA pays out against the hub, while the project actually
    sells its output at its own node. Basis is the gap that leaves unhedged.
    Negative basis means the node clears below the hub -- the project earns
    less than the contract settles against.

    Solar-heavy pockets tend to run most negative exactly when solar
    generates, which is why cost_of_basis() weights by generation rather than
    by hour.
    """
    if not node_price.index.equals(hub_price.index):
        raise ValueError(
            "node_price and hub_price indexes do not match -- both must cover "
            "the same hours before differencing them"
        )
    return (node_price - hub_price).rename("basis")


def cost_of_basis(basis_series: pd.Series, generation_mwh: pd.Series) -> float:
    """Generation-weighted average basis in $/MWh.

    Signed, not flipped: a negative result means the project realizes less
    per MWh than the hub the contract settles against, i.e. basis costs it
    money. Weighting by generation rather than by hour is the point -- basis
    during hours the plant is dark costs the project nothing.
    """
    return _generation_weighted_average(basis_series, generation_mwh)


def negative_basis_hours(basis_series: pd.Series) -> int:
    """Count of hours the node cleared strictly below the hub."""
    return int((basis_series < 0).sum())
