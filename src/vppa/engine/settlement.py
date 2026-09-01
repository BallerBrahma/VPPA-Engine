"""The one settlement function everything else derives from."""

import pandas as pd


def settle(
    generation_mwh: pd.Series,
    index_price: pd.Series,
    strike: float,
    floor: float | None = None,
) -> pd.DataFrame:
    """Returns hourly frame: index_price, generation, unit_diff, cash_to_buyer.

    A VPPA is a financial swap layered on top of real market sales: the
    generator sells actual output into the market at ``index_price``, and the
    swap separately exchanges (index_price - strike) per MWh of that same
    actual output. Settlement volume is whatever generation shows up each
    hour, not a fixed notional -- that's the shape risk this whole engine
    exists to quantify, so it is never smoothed or averaged here.

    ``floor`` applies a contractual negative-price floor to the settlement
    calculation only (protects the buyer from paying the seller extra when
    the market goes deeply negative). The returned ``index_price`` column is
    always the raw, unfloored series -- negative prices are a central result
    for capture-rate analysis and must not be clipped away.
    """
    if not generation_mwh.index.equals(index_price.index):
        raise ValueError(
            "generation_mwh and index_price indexes do not match "
            "(mismatched length or misaligned hours) -- check interval "
            "convention and timezone alignment before settling"
        )

    effective_price = index_price if floor is None else index_price.clip(lower=floor)
    unit_diff = effective_price - strike
    cash_to_buyer = unit_diff * generation_mwh

    return pd.DataFrame(
        {
            "index_price": index_price,
            "generation": generation_mwh,
            "unit_diff": unit_diff,
            "cash_to_buyer": cash_to_buyer,
        },
        index=generation_mwh.index,
    )
