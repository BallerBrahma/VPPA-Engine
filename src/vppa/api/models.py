"""Request and response schemas for the HTTP API.

Contract itself is reused from vppa.model rather than redefined -- it is
already a pydantic model, so FastAPI validates an incoming contract with
exactly the same rules the CLI applies.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from vppa.model import Contract


class AnalysisRequest(BaseModel):
    """One contract-year to analyse. The full contract travels in the body so
    an edited or uploaded deal needs no server-side storage."""

    contract: Contract
    year: int = Field(ge=1990, le=2100)
    settle_at_node: bool = False
    weather: Literal["tmy", "actual"] = "tmy"


class ContractSummary(BaseModel):
    """A contract plus the handful of derived facts the picker shows on a card,
    computed server-side so the browser never re-derives a number."""

    file: str
    contract: Contract
    label: str
    location: str | None
    zone: str | None
    contract_mw: float
    tracking: str
    has_storage: bool
    storage_mw: float | None
    term_start: str
    term_end: str
    settles_at: str
    settlement_point: str
    commercial_operation: str | None


class OptionAvailability(BaseModel):
    """Whether one control can be used, and -- when it cannot -- why, in words
    meant for the person looking at the greyed-out control."""

    available: bool
    cached: bool = False
    reason: str | None = None


class YearAvailabilityRow(BaseModel):
    year: int
    in_term: bool
    analysis: OptionAvailability
    actual_weather: OptionAvailability
    node_settlement: OptionAvailability


class AvailabilityResponse(BaseModel):
    """What this contract can actually be run against, decided before any
    fetch so the UI can disable a control instead of failing an analysis."""

    contract_name: str
    default_year: int | None
    storage: OptionAvailability
    years: list[YearAvailabilityRow]


class AvailabilityRequest(BaseModel):
    contract: Contract


class MonthRow(BaseModel):
    month: str
    generation_mwh: float
    realized_price_usd_mwh: float | None
    avg_market_price_usd_mwh: float
    cash_to_buyer_usd: float


class SettlementResponse(BaseModel):
    contract_name: str
    year: int
    settlement_point: str
    counterparty: str
    strike_usd_mwh: float
    base_strike_usd_mwh: float
    capture_rate: float
    breakeven_strike_usd_mwh: float
    generation_mwh: float
    cash_to_counterparty_usd: float
    hours: int
    in_term: bool
    notes: list[str]
    monthly: list[MonthRow]


class BasisMonthRow(BaseModel):
    month: str
    mean_basis_usd_mwh: float


class BasisResponse(BaseModel):
    cost_of_basis_usd_mwh: float
    mean_basis_usd_mwh: float
    negative_basis_hours: int
    negative_basis_share: float
    hours: int
    monthly: list[BasisMonthRow]


class ScenarioRow(BaseModel):
    scenario: str
    label: str
    generation_mwh: float
    capture_rate: float
    breakeven_strike_usd_mwh: float
    cash_to_buyer_usd: float


class ScenariosResponse(BaseModel):
    scenarios: list[ScenarioRow]


class HourRow(BaseModel):
    hour: int
    generation_mwh: float
    delivered_mwh: float


class StorageResponse(BaseModel):
    power_mw: float
    energy_capacity_mwh: float
    round_trip_efficiency: float
    capture_rate_base: float
    capture_rate_with_storage: float
    uplift_points: float
    revenue_uplift_usd: float
    round_trip_loss_mwh: float
    cycles: float
    average_day: list[HourRow]
