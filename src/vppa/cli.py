"""`vppa settle contracts/x.yaml --year 2024`"""

from __future__ import annotations

import pandas as pd
import typer

from vppa.engine.metrics import breakeven_strike, capture_rate
from vppa.engine.settlement import settle
from vppa.ingest.generation import fetch_pvwatts_generation
from vppa.ingest.prices import fetch_ercot_hub_dam_prices
from vppa.model import Contract, load_contract
from vppa.report.statement import monthly_statement

app = typer.Typer()


def _aligned_price_series(generation: pd.Series, price: pd.Series) -> pd.Series:
    """Reconcile TMY generation's synthetic calendar against a real ISO year.

    Phase 1 generation comes from typical-year (TMY) weather stamped onto the
    region's real prevailing timezone (see ingest/generation.py) -- it can't
    represent a leap year's Feb 29, and the DST reconciliation there drops
    one hour a real civil year would have. Both are treated as generation's
    calendar being authoritative: any real price hour generation has no
    counterpart for is dropped, visibly, rather than left for settle() to
    reject as an unexplained length mismatch.
    """
    if generation.index.equals(price.index):
        return price

    extra_in_price = ~price.index.isin(generation.index)
    dropped = int(extra_in_price.sum())
    if dropped == 0:
        raise ValueError(
            "generation has hours with no matching price data -- "
            "check that both series cover the same year"
        )
    typer.echo(
        f"Dropping {dropped} price hour(s) with no TMY-calendar counterpart "
        "(leap day and/or DST reconciliation -- see README assumptions)"
    )
    aligned = price[~extra_in_price]
    if not aligned.index.equals(generation.index):
        raise ValueError(
            "generation has hours with no matching price data even after "
            "dropping price's extra hours -- check both series' years"
        )
    return aligned


def _settle_contract(contract: Contract, year: int) -> pd.DataFrame:
    generation = fetch_pvwatts_generation(contract, year).series
    price = fetch_ercot_hub_dam_prices(contract.settlement_point, year).series
    price = _aligned_price_series(generation, price)
    settled = settle(generation, price, strike=contract.strike_usd_mwh, floor=contract.negative_price_floor)

    # a few hours near midnight local time land in UTC on the neighboring
    # calendar year (see ingest/generation.py's DST handling); trim to the
    # target year so a report titled `year` doesn't carry a stray sliver of
    # the next one.
    return settled[settled.index.year == year]


@app.command()
def settle_contract(
    contract_path: str = typer.Argument(..., help="Path to a contract YAML file"),
    year: int = typer.Option(..., "--year", help="Calendar year to settle"),
) -> None:
    """Settle one contract for one year: ingest, align, settle, report."""
    contract = load_contract(contract_path)
    settled = _settle_contract(contract, year)

    typer.echo(monthly_statement(settled).to_string(float_format=lambda x: f"{x:,.2f}"))

    generation, price = settled["generation"], settled["index_price"]
    rate = capture_rate(generation, price)
    breakeven = breakeven_strike(generation, price, floor=contract.negative_price_floor)
    typer.echo(f"\nAnnual capture rate: {rate:.1%}")
    typer.echo(
        f"Breakeven strike: ${breakeven:.2f}/MWh "
        f"(contract strike: ${contract.strike_usd_mwh:.2f}/MWh)"
    )


if __name__ == "__main__":
    app()
