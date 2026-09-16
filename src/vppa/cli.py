"""`vppa settle contracts/x.yaml --year 2024`"""

from __future__ import annotations

import pandas as pd
import typer

from vppa.align import align_price_to_generation, trim_to_year
from vppa.engine.curtailment import curtailment_summary, economic_curtailment
from vppa.engine.dispatch import foresight_premium, storage_uplift
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


def _settle_contract(
    contract: Contract, year: int, weather: str = "tmy"
) -> pd.DataFrame:
    generation = fetch_pvwatts_generation(contract, year, weather=weather).series
    # trim first so every price feed is reconciled to the same calendar year
    generation = trim_to_year(generation, year)
    price = fetch_ercot_hub_dam_prices(contract.settlement_point, year).series
    price, notes = align_price_to_generation(generation, price)
    for note in notes:
        typer.echo(note)

    gross = generation
    if contract.curtailment is not None:
        split = economic_curtailment(
            generation, price, contract.curtailment.curtail_below_usd_mwh
        )
        summary = curtailment_summary(split, price)
        typer.echo(
            f"Curtailed {summary['curtailed_mwh']:,.0f} MWh "
            f"({summary['curtailed_share']:.1%}) over {summary['curtailed_hours']:,} "
            f"hours below ${contract.curtailment.curtail_below_usd_mwh:.2f}/MWh, "
            f"avoiding ${summary['revenue_saved_usd']:,.0f} of negative revenue"
        )
        generation = split["delivered"]

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
    # Carry the uncurtailed series through as well. The battery has to be
    # offered energy the plant would otherwise have spilled -- absorbing it is
    # a large part of what storage is for -- so dispatching on the delivered
    # series would quietly answer a different, worse question.
    settled["generation_gross"] = gross
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
        threshold = (
            contract.curtailment.curtail_below_usd_mwh if contract.curtailment else 0.0
        )
        # gross, not delivered: the LP decides for itself whether an hour is
        # stored or spilled, which is exactly the trade-off being measured
        gross = settled["generation_gross"]
        uplift = storage_uplift(
            gross, price, contract.storage, curtail_below_usd_mwh=threshold
        )
        premium = foresight_premium(
            gross, price, contract.storage, curtail_below_usd_mwh=threshold
        )
        typer.echo(
            f"\nWith {contract.storage.power_mw:.0f} MW / "
            f"{contract.storage.energy_capacity_mwh:.0f} MWh storage: "
            f"capture rate {uplift['capture_rate_with_storage']:.1%} "
            f"(+{(uplift['capture_rate_with_storage'] - uplift['capture_rate_base']) * 100:.1f} pp), "
            f"revenue +${uplift['revenue_uplift_usd'] / 1e6:,.2f}M"
        )
        typer.echo(
            f"  Solved a day at a time instead: "
            f"+${premium['revenue_uplift_daily_usd'] / 1e6:,.2f}M "
            f"(${premium['foresight_premium_usd'] / 1e6:,.2f}M of the figure above is "
            f"foresight nobody has)"
        )
        if contract.storage.cycling_cost_usd_mwh:
            typer.echo(
                f"  Degradation charged at "
                f"${contract.storage.cycling_cost_usd_mwh:.2f}/MWh throughput: "
                f"${uplift['cycling_cost_usd']:,.0f}"
            )
        else:
            typer.echo("  (no cycling cost set -- wear is being treated as free)")


if __name__ == "__main__":
    app()
