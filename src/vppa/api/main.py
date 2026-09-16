"""HTTP API over the settlement engine.

Every endpoint is a thin wrapper: it resolves inputs, calls the same engine
functions the CLI calls, and serialises the result. No analysis lives here,
so the API cannot drift from `vppa settle`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from vppa import store
from vppa.align import align_price_to_generation, trim_to_year
from vppa.api.models import (
    AnalysisRequest,
    AvailabilityRequest,
    AvailabilityResponse,
    BasisMonthRow,
    BasisResponse,
    ContractSummary,
    HourRow,
    MonthRow,
    OptionAvailability,
    ScenarioRow,
    ScenariosResponse,
    SettlementResponse,
    StorageResponse,
    YearAvailabilityRow,
)
from vppa.availability import offered_years, year_availability
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
from vppa.ingest.prices import fetch_ercot_dam_prices, fetch_ercot_hub_dam_prices
from vppa.ingest.settlement_points import fetch_settlement_points, known_nodes
from vppa.model import Contract, load_contract
from vppa.report.statement import monthly_statement

# repo root, not the cwd -- see the note on store.DATA_DIR
CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"

SCENARIO_LABELS = {
    "base": "Base case",
    "p90_production": "P90 production",
    "price_collapse": "Price collapse (-30%)",
    "bad_basis_year": "Bad basis year (-$10/MWh)",
    "combined_stress": "Combined stress",
}

app = FastAPI(
    title="Solar VPPA Settlement & Basis API",
    description="Settles virtual PPAs for utility-scale solar and quantifies "
    "the basis and shape risk in them.",
    version="0.1.0",
)

# The Next.js dev server runs on a different origin; in production the two are
# served together and this is a no-op.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve(request: AnalysisRequest):
    """Fetch and align one contract-year, or fail with a readable message.

    Ingest errors (a missing API key, an unknown settlement point) are the
    common case here and must reach the client as 400s, not 500s -- they are
    bad inputs or missing configuration, not server faults.
    """
    contract = request.contract
    try:
        generation = fetch_pvwatts_generation(
            contract, request.year, weather=request.weather
        ).series
        hub = fetch_ercot_hub_dam_prices(contract.hub, request.year).series
        node = (
            fetch_ercot_dam_prices(contract.node, request.year).series
            if request.settle_at_node
            else None
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # trim before aligning: the feeds disagree about the year boundary, so
    # settling that difference first keeps every source on the same calendar
    generation = trim_to_year(generation, request.year)
    index_price = node if request.settle_at_node else hub
    index_price, notes = align_price_to_generation(generation, index_price)

    index = generation.index
    if node is not None:
        node = node[node.index.isin(index)]
        hub = hub[hub.index.isin(index)]

    return contract, generation, index_price.loc[index], hub, node, notes


def _node_zones() -> dict[str, str]:
    """node -> ERCOT load zone, or {} if the registry has never been pulled.

    A missing registry degrades the cards (no zone badge) and makes the node
    check permissive; it must never take the picker down.
    """
    try:
        registry = fetch_settlement_points()
    except Exception:  # noqa: BLE001 -- offline is a normal state here
        return {}
    return dict(zip(registry["node"], registry["zone"], strict=False))


def _summarise(file: str, contract: Contract, zones: dict[str, str]) -> ContractSummary:
    return ContractSummary(
        file=file,
        contract=contract,
        label=contract.label,
        location=contract.location_label,
        zone=zones.get(contract.node),
        contract_mw=contract.contract_mw,
        tracking=contract.project.tracking,
        has_storage=contract.storage is not None,
        storage_mw=contract.storage.power_mw if contract.storage else None,
        term_start=contract.term.start.isoformat(),
        term_end=contract.term.end.isoformat(),
        settles_at=contract.settlement_index,
        settlement_point=contract.settlement_point,
        commercial_operation=(
            contract.project.commercial_operation.isoformat()
            if contract.project.commercial_operation
            else None
        ),
    )


def _as_option(option) -> OptionAvailability:
    return OptionAvailability(
        available=option.available, cached=option.cached, reason=option.reason
    )


@app.post("/api/availability", response_model=AvailabilityResponse)
def availability(request: AvailabilityRequest) -> AvailabilityResponse:
    """What this contract supports, per year, before anything is fetched.

    The UI disables controls from this rather than letting a run fail: a node
    that is not in ERCOT's registry, a year the plant predates, and weather
    NSRDB has not published yet are all knowable for free.
    """
    contract = request.contract
    # known_nodes() returns an empty set rather than raising when the registry
    # is unreachable, and an empty set is permissive by design
    nodes = known_nodes()
    cached = store.cached_partitions()

    rows = [
        year_availability(contract, year, known_nodes=nodes, cached=cached)
        for year in offered_years()
    ]
    runnable = [r for r in rows if r.analysis.available]
    in_term = [r for r in runnable if r.in_term]
    default = (in_term or runnable)[0].year if runnable else None

    return AvailabilityResponse(
        contract_name=contract.name,
        default_year=default,
        storage=OptionAvailability(
            available=contract.storage is not None,
            reason=None
            if contract.storage
            else "This contract has no paired battery to dispatch",
        ),
        years=[
            YearAvailabilityRow(
                year=row.year,
                in_term=row.in_term,
                analysis=_as_option(row.analysis),
                actual_weather=_as_option(row.actual_weather),
                node_settlement=_as_option(row.node_settlement),
            )
            for row in rows
        ],
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/contracts", response_model=list[ContractSummary])
def list_contracts() -> list[ContractSummary]:
    """Contracts shipped in the repo, for the picker."""
    if not CONTRACTS_DIR.is_dir():
        return []
    zones = _node_zones()
    summaries = []
    for path in sorted(CONTRACTS_DIR.glob("*.yaml")):
        try:
            summaries.append(_summarise(path.name, load_contract(path), zones))
        except (yaml.YAMLError, ValueError) as exc:
            # a malformed file on disk shouldn't take the whole picker down
            raise HTTPException(
                status_code=500, detail=f"{path.name} is not a valid contract: {exc}"
            ) from exc
    return summaries


@app.post("/api/settlement", response_model=SettlementResponse)
def settlement(request: AnalysisRequest) -> SettlementResponse:
    contract, generation, price, _hub, _node, notes = _resolve(request)

    strike = contract.strike_for_year(request.year)
    settled = settle(
        generation, price, strike=strike, floor=contract.negative_price_floor
    )
    statement = monthly_statement(settled)

    return SettlementResponse(
        contract_name=contract.name,
        year=request.year,
        settlement_point=contract.node if request.settle_at_node else contract.hub,
        counterparty=contract.counterparty_view,
        strike_usd_mwh=strike,
        base_strike_usd_mwh=contract.strike_usd_mwh,
        capture_rate=capture_rate(generation, price),
        breakeven_strike_usd_mwh=breakeven_strike(
            generation, price, floor=contract.negative_price_floor
        ),
        generation_mwh=float(generation.sum()),
        cash_to_counterparty_usd=float(
            settled["cash_to_buyer"].sum() * contract.counterparty_sign
        ),
        hours=len(generation),
        in_term=contract.covers_year(request.year),
        notes=notes,
        monthly=[
            MonthRow(
                month=index.strftime("%b %Y"),
                generation_mwh=float(row["generation_mwh"]),
                realized_price_usd_mwh=(
                    None
                    if pd.isna(row["realized_price_usd_mwh"])
                    else float(row["realized_price_usd_mwh"])
                ),
                avg_market_price_usd_mwh=float(row["avg_market_price_usd_mwh"]),
                cash_to_buyer_usd=float(row["cash_to_buyer_usd"]),
            )
            for index, row in statement.iterrows()
        ],
    )


@app.post("/api/basis", response_model=BasisResponse)
def basis_analysis(request: AnalysisRequest) -> BasisResponse:
    if not request.settle_at_node:
        raise HTTPException(
            status_code=400,
            detail="Basis compares node against hub; set settle_at_node to true.",
        )
    _contract, generation, _price, hub, node, _notes = _resolve(request)

    spread = basis(node, hub)
    monthly = spread.resample("MS").mean()

    return BasisResponse(
        cost_of_basis_usd_mwh=cost_of_basis(spread, generation),
        mean_basis_usd_mwh=float(spread.mean()),
        negative_basis_hours=negative_basis_hours(spread),
        negative_basis_share=negative_basis_hours(spread) / len(spread),
        hours=len(spread),
        monthly=[
            BasisMonthRow(month=i.strftime("%b %Y"), mean_basis_usd_mwh=float(v))
            for i, v in monthly.items()
        ],
    )


@app.post("/api/scenarios", response_model=ScenariosResponse)
def scenarios(request: AnalysisRequest) -> ScenariosResponse:
    contract, generation, price, _hub, _node, _notes = _resolve(request)

    table = run_scenarios(
        generation,
        price,
        strike=contract.strike_for_year(request.year),
        floor=contract.negative_price_floor,
    )
    return ScenariosResponse(
        scenarios=[
            ScenarioRow(
                scenario=str(name),
                label=SCENARIO_LABELS.get(str(name), str(name)),
                generation_mwh=float(row["generation_mwh"]),
                capture_rate=float(row["capture_rate"]),
                breakeven_strike_usd_mwh=float(row["breakeven_strike"]),
                cash_to_buyer_usd=float(row["cash_to_buyer_usd"]),
            )
            for name, row in table.iterrows()
        ]
    )


@app.post("/api/storage", response_model=StorageResponse)
def storage(request: AnalysisRequest) -> StorageResponse:
    contract, generation, price, _hub, _node, _notes = _resolve(request)
    if contract.storage is None:
        raise HTTPException(
            status_code=400,
            detail="This contract has no storage block to dispatch.",
        )

    spec = contract.storage
    uplift = storage_uplift(generation, price, spec)
    profile = dispatch(generation, price, spec)
    day = profile.groupby(profile.index.hour)[["generation", "delivered"]].mean()

    return StorageResponse(
        power_mw=spec.power_mw,
        energy_capacity_mwh=spec.energy_capacity_mwh,
        round_trip_efficiency=spec.round_trip_efficiency,
        capture_rate_base=uplift["capture_rate_base"],
        capture_rate_with_storage=uplift["capture_rate_with_storage"],
        uplift_points=(
            uplift["capture_rate_with_storage"] - uplift["capture_rate_base"]
        ) * 100,
        revenue_uplift_usd=uplift["revenue_uplift_usd"],
        round_trip_loss_mwh=uplift["round_trip_loss_mwh"],
        cycles=uplift["cycles"],
        average_day=[
            HourRow(
                hour=int(hour),
                generation_mwh=float(row["generation"]),
                delivered_mwh=float(row["delivered"]),
            )
            for hour, row in day.iterrows()
        ],
    )


@app.post("/api/contracts/validate", response_model=Contract)
def validate_contract(contract: Contract) -> Contract:
    """Echo a contract back if it validates. The editor uses this to check a
    deal before paying for a full analysis."""
    return contract
