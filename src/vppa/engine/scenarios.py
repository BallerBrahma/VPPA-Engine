"""scenarios(): P90 production, bad-basis year, price-collapse cases over settle()."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from vppa.engine.metrics import breakeven_strike, capture_rate
from vppa.engine.settlement import settle

# Standard-normal z at the 90th percentile. A P90 year is the production level
# exceeded in 90 of 100 years, i.e. 1.2816 standard deviations below the mean.
_Z_P90 = 1.2816

# Interannual variability of annual solar production. 7% is a common
# utility-scale planning assumption; it belongs to the project, not to this
# module, so it is always passed in explicitly at the call site.
DEFAULT_INTERANNUAL_CV = 0.07


def p90_factor(interannual_cv: float = DEFAULT_INTERANNUAL_CV) -> float:
    """Scale factor turning a P50 (median) production profile into a P90 one.

    Applied as a flat scalar on every hour: it models a dimmer year, not a
    differently-shaped one. Real weather variation changes shape as well as
    level, so this understates the risk to capture rate specifically.
    """
    if not 0 <= interannual_cv < 1 / _Z_P90:
        raise ValueError(f"interannual_cv must be in [0, {1 / _Z_P90:.3f}), got {interannual_cv}")
    return 1.0 - _Z_P90 * interannual_cv


@dataclass(frozen=True)
class Scenario:
    """A named stress applied to settle()'s inputs.

    Deliberately expressed as transformations of the inputs rather than of the
    settled frame: the whole engine has one settlement path, and a scenario
    that edited results afterwards could drift away from what settle() would
    actually compute.
    """

    name: str
    generation_factor: float = 1.0
    price_factor: float = 1.0
    basis_shift_usd_mwh: float = 0.0

    def apply(
        self, generation_mwh: pd.Series, price: pd.Series
    ) -> tuple[pd.Series, pd.Series]:
        """Return (generation, price) with this scenario's stresses applied.

        The basis shift is additive and applied after the price factor, since
        congestion is a $/MWh spread against the hub rather than a proportion
        of the price level -- and it must still be able to push a price
        negative, which is a real outcome, not an error.
        """
        return (
            generation_mwh * self.generation_factor,
            price * self.price_factor + self.basis_shift_usd_mwh,
        )


def standard_scenarios(
    interannual_cv: float = DEFAULT_INTERANNUAL_CV,
    price_collapse: float = 0.30,
    bad_basis_usd_mwh: float = 10.0,
) -> list[Scenario]:
    """The three cases the design calls for, plus the base and a combined stress."""
    p90 = p90_factor(interannual_cv)
    return [
        Scenario("base"),
        Scenario("p90_production", generation_factor=p90),
        Scenario("price_collapse", price_factor=1.0 - price_collapse),
        Scenario("bad_basis_year", basis_shift_usd_mwh=-abs(bad_basis_usd_mwh)),
        Scenario(
            "combined_stress",
            generation_factor=p90,
            price_factor=1.0 - price_collapse,
            basis_shift_usd_mwh=-abs(bad_basis_usd_mwh),
        ),
    ]


def run_scenarios(
    generation_mwh: pd.Series,
    price: pd.Series,
    strike: float,
    floor: float | None = None,
    scenarios: list[Scenario] | None = None,
) -> pd.DataFrame:
    """Settle the same contract under each scenario, one row per case.

    Returns generation, realized price, capture rate, breakeven strike and
    total cash to the buyer -- so the question "which stress actually moves
    the P&L" is answerable by reading down a column.
    """
    scenarios = scenarios or standard_scenarios()

    rows = []
    for scenario in scenarios:
        stressed_generation, stressed_price = scenario.apply(generation_mwh, price)
        settled = settle(stressed_generation, stressed_price, strike=strike, floor=floor)
        rows.append(
            {
                "scenario": scenario.name,
                "generation_mwh": stressed_generation.sum(),
                "capture_rate": capture_rate(stressed_generation, stressed_price),
                "breakeven_strike": breakeven_strike(
                    stressed_generation, stressed_price, floor=floor
                ),
                "cash_to_buyer_usd": settled["cash_to_buyer"].sum(),
            }
        )

    return pd.DataFrame(rows).set_index("scenario")
