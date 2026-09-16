"""Economic curtailment: the hours a plant chooses not to export.

A solar plant is not obliged to generate. When the settlement price is below
what the operator nets per MWh, exporting destroys value and the plant curtails
instead. That matters here because those hours are precisely the ones this
project is about -- the saturated midday hours where solar suppresses its own
price -- so a model that exports through them overstates both volume and loss.

Only *economic* curtailment is modelled. ERCOT also curtails for congestion and
reliability reasons that have nothing to do with price, and none of that is
here; treat the figures below as a lower bound on real curtailment.
"""

from __future__ import annotations

import pandas as pd


def economic_curtailment(
    generation_mwh: pd.Series,
    price: pd.Series,
    curtail_below_usd_mwh: float = 0.0,
) -> pd.DataFrame:
    """Split generation into what is exported and what is curtailed.

    The plant exports in any hour where `price >= curtail_below_usd_mwh` and
    curtails entirely otherwise. Curtailment is all-or-nothing per hour because
    the decision is about the sign of the margin, not its size: if exporting a
    megawatt-hour loses money, so does exporting a fraction of one.

    `curtail_below_usd_mwh` is the operator's walk-away price, not the market's.
    A merchant plant walks away at 0. A project earning the production tax
    credit keeps generating well into negative prices, because the credit is
    earned per megawatt-hour produced and outweighs the loss -- which is a
    large part of why ERCOT sees negative prices at all. Represent that with a
    negative threshold (around -27.50 for the 2024 PTC), not by pretending the
    plant is irrational.

    Returns an hourly frame: generation, delivered, curtailed.
    """
    if not generation_mwh.index.equals(price.index):
        raise ValueError(
            "generation_mwh and price indexes do not match -- align them "
            "before applying curtailment"
        )

    exports = price >= curtail_below_usd_mwh
    delivered = generation_mwh.where(exports, 0.0)

    return pd.DataFrame(
        {
            "generation": generation_mwh,
            "delivered": delivered,
            "curtailed": generation_mwh - delivered,
        },
        index=generation_mwh.index,
    )


def curtailment_summary(
    curtailed: pd.DataFrame, price: pd.Series
) -> dict[str, float]:
    """Headline numbers for a curtailment run.

    `revenue_saved_usd` is positive whenever curtailment helps, which it always
    does at a threshold of zero: every curtailed hour was one the plant would
    have exported into a price below its walk-away point. The volume loss is
    real, but so is the loss it avoids.
    """
    generation = float(curtailed["generation"].sum())
    delivered = float(curtailed["delivered"].sum())
    hours = int((curtailed["curtailed"] > 0).sum())

    revenue_exported = float((curtailed["delivered"] * price).sum())
    revenue_uncurtailed = float((curtailed["generation"] * price).sum())

    return {
        "generation_mwh": generation,
        "delivered_mwh": delivered,
        "curtailed_mwh": generation - delivered,
        "curtailed_share": (generation - delivered) / generation if generation else 0.0,
        "curtailed_hours": hours,
        "revenue_saved_usd": revenue_exported - revenue_uncurtailed,
    }
