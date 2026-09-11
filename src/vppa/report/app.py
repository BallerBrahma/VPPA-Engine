"""Streamlit front end: `streamlit run src/vppa/report/app.py`.

A thin shell over the engine -- it fetches, aligns and displays, but computes
nothing itself. Every number shown comes from settle(), metrics or scenarios,
so the UI cannot drift away from what the CLI reports.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit executes this file as a script rather than importing the package,
# so make a plain checkout runnable without relying on the editable install.
_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st

from vppa.engine.dispatch import dispatch, storage_uplift
from vppa.engine.metrics import (
    basis,
    breakeven_strike,
    capture_rate,
    cost_of_basis,
    negative_basis_hours,
)
from vppa.engine.scenarios import run_scenarios
from vppa.engine.settlement import settle
from vppa.ingest.generation import fetch_pvwatts_generation
from vppa.ingest.prices import (
    fetch_ercot_dam_prices,
    fetch_ercot_hub_dam_prices,
)
from vppa.model import load_contract
from vppa.report.statement import monthly_statement

CONTRACTS_DIR = _SRC.parent / "contracts"


@st.cache_data(show_spinner=False)
def _load(contract_path: str, year: int, use_node: bool):
    """Fetch and align one contract-year. Cached because a cold run pulls a
    year of prices and a PVWatts simulation."""
    contract = load_contract(contract_path)
    generation = fetch_pvwatts_generation(contract, year).series
    hub = fetch_ercot_hub_dam_prices(contract.hub, year).series
    node = fetch_ercot_dam_prices(contract.node, year).series if use_node else None

    index = generation.index.intersection(hub.index)
    if node is not None:
        index = index.intersection(node.index)
    index = index[index.year == year]

    return (
        contract,
        generation.loc[index],
        hub.loc[index],
        None if node is None else node.loc[index],
    )


st.set_page_config(page_title="Solar VPPA Settlement", layout="wide")
st.title("Solar VPPA Settlement & Basis")

contract_files = sorted(p.name for p in CONTRACTS_DIR.glob("*.yaml"))
if not contract_files:
    st.error(f"No contract YAML files found in {CONTRACTS_DIR}")
    st.stop()

with st.sidebar:
    st.header("Contract")
    chosen = st.selectbox("Contract", contract_files)
    year = st.selectbox("Year", [2025, 2024, 2023], index=0)
    settle_at_node = st.toggle(
        "Settle at node", value=False,
        help="Off settles against the hub (the common structure, which leaves "
             "the project carrying basis). On settles at the project's own node.",
    )
    st.caption(
        "Generation is a typical (TMY) year, not the actual weather of the "
        "selected year — see the README's stated assumptions."
    )

try:
    contract, generation, hub, node = _load(
        str(CONTRACTS_DIR / chosen), year, settle_at_node
    )
except Exception as exc:  # noqa: BLE001 -- a UI should surface any load
    # failure (missing API key, network, bad contract) as a readable message
    # rather than a raw traceback in the browser.
    st.error(f"Could not load data: {exc}")
    st.stop()

index_price = node if settle_at_node else hub
settlement_point = contract.node if settle_at_node else contract.hub

settled = settle(
    generation, index_price, strike=contract.strike_usd_mwh,
    floor=contract.negative_price_floor,
)
rate = capture_rate(generation, index_price)
breakeven = breakeven_strike(
    generation, index_price, floor=contract.negative_price_floor
)

st.subheader(f"{contract.name} — {year}, settled at {settlement_point}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Capture rate", f"{rate:.1%}")
c2.metric(
    "Breakeven strike", f"${breakeven:,.2f}",
    delta=f"${breakeven - contract.strike_usd_mwh:,.2f} vs contract",
    delta_color="normal",
)
c3.metric("Generation", f"{generation.sum():,.0f} MWh")
c4.metric("Cash to buyer", f"${settled['cash_to_buyer'].sum() / 1e6:,.2f}M")

if breakeven < contract.strike_usd_mwh:
    st.warning(
        f"The contract strike (${contract.strike_usd_mwh:,.2f}/MWh) is above the "
        f"breakeven strike (${breakeven:,.2f}/MWh): on this production shape the "
        "deal is underwater for the buyer."
    )

tab_statement, tab_basis, tab_scenarios, tab_storage = st.tabs(
    ["Monthly statement", "Basis", "Scenarios", "Storage"]
)

with tab_statement:
    statement = monthly_statement(settled)
    st.dataframe(
        statement.style.format(
            {
                "generation_mwh": "{:,.0f}",
                "realized_price_usd_mwh": "${:,.2f}",
                "avg_market_price_usd_mwh": "${:,.2f}",
                "cash_to_buyer_usd": "${:,.0f}",
            }
        ),
        width="stretch",
    )
    st.caption(
        "Realized price is generation-weighted; average market price is a plain "
        "hourly mean. The gap between the two columns is the shape effect."
    )
    # both columns are $/MWh, so one shared axis is correct here
    st.line_chart(
        statement[["realized_price_usd_mwh", "avg_market_price_usd_mwh"]],
        height=320,
    )

with tab_basis:
    if node is None:
        st.info("Enable **Settle at node** in the sidebar to load nodal prices.")
    else:
        spread = basis(node, hub)
        b1, b2, b3 = st.columns(3)
        b1.metric("Cost of basis", f"${cost_of_basis(spread, generation):,.2f}/MWh")
        b2.metric("Mean basis", f"${spread.mean():,.2f}/MWh")
        b3.metric(
            "Negative-basis hours",
            f"{negative_basis_hours(spread):,}",
            delta=f"{negative_basis_hours(spread) / len(spread):.0%} of hours",
            delta_color="off",
        )
        st.caption(
            "Cost of basis is generation-weighted; mean basis is not. When the "
            "first is worse than the second, congestion is landing in the hours "
            "the plant is actually running."
        )
        st.line_chart(
            spread.resample("MS").mean().rename("mean basis ($/MWh)"), height=320
        )

with tab_scenarios:
    scenarios = run_scenarios(
        generation, index_price, strike=contract.strike_usd_mwh,
        floor=contract.negative_price_floor,
    )
    display = scenarios.copy()
    display["cash_to_buyer_usd"] = display["cash_to_buyer_usd"] / 1e6
    display = display.rename(columns={"cash_to_buyer_usd": "cash_to_buyer_musd"})
    st.dataframe(
        display.style.format(
            {
                "generation_mwh": "{:,.0f}",
                "capture_rate": "{:.1%}",
                "breakeven_strike": "${:,.2f}",
                "cash_to_buyer_musd": "${:,.2f}M",
            }
        ),
        width="stretch",
    )
    st.caption(
        "A P90 year can *improve* the buyer's position on an underwater deal — "
        "less production means less volume to pay out on. P90 is a downside "
        "case for the seller, which is why these are read per counterparty "
        "rather than as one 'bad case' number."
    )


with tab_storage:
    if contract.storage is None:
        st.info(
            "This contract has no `storage:` block. Add one to the contract YAML "
            "(power_mw, duration_hours, round_trip_efficiency) to model the overlay."
        )
    else:
        spec = contract.storage
        uplift = storage_uplift(generation, index_price, spec)
        gain_pp = (
            uplift["capture_rate_with_storage"] - uplift["capture_rate_base"]
        ) * 100

        s1, s2, s3 = st.columns(3)
        s1.metric(
            "Capture rate with storage",
            f"{uplift['capture_rate_with_storage']:.1%}",
            delta=f"{gain_pp:+.1f} pp",
        )
        s2.metric("Revenue uplift", f"${uplift['revenue_uplift_usd'] / 1e6:,.2f}M")
        s3.metric(
            "Round-trip loss",
            f"{uplift['round_trip_loss_mwh']:,.0f} MWh",
            delta=f"{uplift['cycles']:,.0f} cycles",
            delta_color="off",
        )
        st.caption(
            f"{spec.power_mw:,.0f} MW / {spec.energy_capacity_mwh:,.0f} MWh, "
            f"{spec.round_trip_efficiency:.0%} round-trip, charging only from the "
            "project's own output."
        )
        st.warning(
            "Upper bound, not a forecast: the LP dispatches against the whole "
            "year's realised prices with perfect foresight, and carries no "
            "degradation, cycling cost or capex."
        )

        profile = dispatch(generation, index_price, spec)
        day = profile.groupby(profile.index.hour)[["generation", "delivered"]].mean()
        day.index.name = "hour (UTC)"
        st.caption("Average day: storage moves output out of midday into the peak.")
        st.line_chart(day, height=320)
