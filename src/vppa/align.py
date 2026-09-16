"""Reconcile a generation calendar against a real ISO price calendar.

Shared by every front end (CLI, API) so they cannot disagree about which
hours were dropped. Returns notes rather than printing them, leaving
presentation to the caller.
"""

from __future__ import annotations

import pandas as pd


def trim_to_year(series: pd.Series, year: int) -> pd.Series:
    """Keep only hours stamped with `year` in UTC.

    Generation stamped onto a US calendar spills a few hours into the next
    UTC year (local Dec 31 evening is Jan 1 UTC). Price feeds disagree about
    whether those hours belong to the year: ERCOT's archive is a Central-time
    year and includes them, while a UTC-bounded nodal query does not. Trimming
    generation first makes the analysis mean "calendar year in UTC" for every
    source, instead of depending on which feed was asked.
    """
    return series[series.index.year == year]


def align_price_to_generation(
    generation_mwh: pd.Series, price: pd.Series
) -> tuple[pd.Series, list[str]]:
    """Trim `price` to the hours `generation_mwh` actually covers.

    Generation comes from an NSRDB year: 8,760 hours, no Feb 29, and one hour
    lost to the DST reconciliation in ingest/generation.py. A real ISO year has
    neither property, so some price hours have no generation counterpart.

    Generation's calendar is treated as authoritative and price conforms to it.
    Any dropped hours are reported in the returned notes rather than silently
    discarded -- and if generation has hours price lacks, that is an error, not
    something to paper over by settling on a partial year.
    """
    if generation_mwh.index.equals(price.index):
        return price, []

    extra_in_price = ~price.index.isin(generation_mwh.index)
    dropped = int(extra_in_price.sum())
    if dropped == 0:
        raise ValueError(
            "generation has hours with no matching price data -- "
            "check that both series cover the same year"
        )

    aligned = price[~extra_in_price]
    if not aligned.index.equals(generation_mwh.index):
        raise ValueError(
            "generation has hours with no matching price data even after "
            "dropping price's extra hours -- check both series' years"
        )

    note = (
        f"Dropped {dropped} price hour(s) with no generation-calendar "
        "counterpart (leap day and/or DST reconciliation)."
    )
    return aligned, [note]
