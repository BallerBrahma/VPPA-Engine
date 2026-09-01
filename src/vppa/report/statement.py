"""Monthly settlement statement rendering."""

from __future__ import annotations

import pandas as pd


def monthly_statement(settled: pd.DataFrame) -> pd.DataFrame:
    """Aggregate settle()'s hourly frame into a monthly statement.

    `settled` is settle()'s output: index_price, generation, unit_diff,
    cash_to_buyer. Returns one row per calendar month with the generation-
    weighted realized price next to the simple time-weighted average price --
    the gap between them, month by month, is the thesis in statement form.
    """
    generation = settled["generation"].resample("MS").sum().rename("generation_mwh")
    cash_to_buyer = settled["cash_to_buyer"].resample("MS").sum().rename("cash_to_buyer_usd")
    avg_market_price = settled["index_price"].resample("MS").mean().rename("avg_market_price_usd_mwh")

    weighted_price_sum = (settled["index_price"] * settled["generation"]).resample("MS").sum()
    realized_price = (weighted_price_sum / generation).rename("realized_price_usd_mwh")

    return pd.concat(
        [generation, realized_price, avg_market_price, cash_to_buyer],
        axis=1,
    )
