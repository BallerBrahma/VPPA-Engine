"""`vppa settle contracts/x.yaml --year 2024`"""

from __future__ import annotations

import pandas as pd
import typer

from vppa.engine.dispatch import storage_uplift
from vppa.engine.metrics import breakeven_strike, capture_rate
from vppa.engine.settlement import settle
from vppa.ingest.generation import fetch_pvwatts_generation
from vppa.ingest.prices import fetch_ercot_hub_dam_prices
from vppa.model import Contract, load_contract
from vppa.report.statement import monthly_statement

app = typer.Typer(help="Solar VPPA settlement and basis engine.")


@app.callback()
def main() -> None:
    """Registered so the CLI keeps subcommand routing (`vppa settle ...`)
    rather than collapsing its single command into the bare entry point."""


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


def _settle_contract(
    contract: Contract, year: int, weather: str = "tmy"
) -> pd.DataFrame:
    generation = fetch_pvwatts_generation(contract, year, weather=weather).series
    price = fetch_ercot_hub_dam_prices(contract.settlement_point, year).series
    price = _aligned_price_series(generation, price)
    settled = settle(
        generation,
        price,
        strike=contract.strike_for_year(year),
        floor=contract.negative_price_floor,
    )

    # a few hours near midnight local time land in UTC on the neighboring
    # calendar year (see ingest/generation.py's DST handling); trim to the
    # target year so a report titled `year` doesn't carry a stray sliver of
    # the next one.
    return settled[settled.index.year == year]


@app.command("settle")
def settle_contract(
    contract_path: str = typer.Argument(..., help="Path to a contract YAML file"),
    year: int = typer.Option(..., "--year", help="Calendar year to settle"),
    weather: str = typer.Option(
        "tmy",
        "--weather",
        help="tmy = typical year (isolates price effects); "
             "actual = that year's real NSRDB weather (for a real P&L)",
    ),
) -> None:
    """Settle one contract for one year: ingest, align, settle, report."""
    contract = load_contract(contract_path)
    if not contract.covers_year(year):
        typer.echo(
            f"Note: {year} falls outside this contract's term "
            f"({contract.term.start} to {contract.term.end}) -- "
            'settling it as a counterfactual.'
        )
    settled = _settle_contract(contract, year, weather=weather)

    typer.echo(monthly_statement(settled).to_string(float_format=lambda x: f"{x:,.2f}"))

    generation, price = settled["generation"], settled["index_price"]
    rate = capture_rate(generation, price)
    breakeven = breakeven_strike(generation, price, floor=contract.negative_price_floor)
    strike = contract.strike_for_year(year)
    escalated = " (escalated)" if strike != contract.strike_usd_mwh else ""

    typer.echo(f"\nAnnual capture rate: {rate:.1%}")
    typer.echo(
        f"Breakeven strike: ${breakeven:.2f}/MWh "
        f"(contract strike: ${strike:.2f}/MWh{escalated})"
    )
    side = contract.counterparty_view
    cash = settled["cash_to_buyer"].sum() * contract.counterparty_sign
    typer.echo(f"Net cash to {side}: ${cash / 1e6:,.2f}M")

    if contract.storage is not None:
        uplift = storage_uplift(generation, price, contract.storage)
        typer.echo(
            f"\nWith {contract.storage.power_mw:.0f} MW / "
            f"{contract.storage.energy_capacity_mwh:.0f} MWh storage: "
            f"capture rate {uplift['capture_rate_with_storage']:.1%} "
            f"(+{(uplift['capture_rate_with_storage'] - uplift['capture_rate_base']) * 100:.1f} pp), "
            f"revenue +${uplift['revenue_uplift_usd'] / 1e6:,.2f}M"
        )
        typer.echo(
            "  (perfect-foresight dispatch, no degradation or capex -- an upper bound)"
        )


if __name__ == "__main__":
    app()
