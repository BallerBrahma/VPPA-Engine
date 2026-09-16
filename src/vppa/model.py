"""Typed domain objects: Contract, GenerationProfile, PriceSeries.

Validation lives here, not in the engine. In particular this is where the
known traps from the design doc get caught before any hourly series reaches
settle(): naive or non-UTC timestamps, duplicate hours from an unhandled DST
fall-back, and missing values.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


def _validate_utc_series(series: pd.Series, label: str) -> pd.Series:
    if not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError(f"{label} must have a DatetimeIndex, got {type(series.index).__name__}")
    if series.index.tz is None or str(series.index.tz) != "UTC":
        raise ValueError(
            f"{label} index must be tz-aware UTC (got {series.index.tz}) -- "
            "store everything in UTC internally, convert only at display"
        )
    if not series.index.is_monotonic_increasing:
        raise ValueError(f"{label} index must be sorted ascending")
    if series.index.has_duplicates:
        raise ValueError(
            f"{label} index has duplicate timestamps -- likely an unhandled "
            "DST fall-back hour"
        )
    if series.isna().any():
        raise ValueError(f"{label} contains missing values")
    return series


class PriceSeries(BaseModel):
    """A UTC-indexed price series in $/MWh. Negative prices are valid and are
    never clipped here -- they are a central result, not bad data."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    settlement_point: str
    series: pd.Series

    @field_validator("series")
    @classmethod
    def _validate_series(cls, v: pd.Series) -> pd.Series:
        return _validate_utc_series(v, label="price series")


class GenerationProfile(BaseModel):
    """A UTC-indexed generation series in MWh."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_name: str
    series: pd.Series

    @field_validator("series")
    @classmethod
    def _validate_series(cls, v: pd.Series) -> pd.Series:
        v = _validate_utc_series(v, label="generation profile")
        if (v < 0).any():
            raise ValueError("generation profile must not contain negative values")
        return v


class Term(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: dt.date
    end: dt.date

    @model_validator(mode="after")
    def _end_after_start(self) -> Term:
        if self.end <= self.start:
            raise ValueError(f"term.end ({self.end}) must be after term.start ({self.start})")
        return self


class ProjectSpec(BaseModel):
    """PVWatts inputs. See design doc section 2 for what each field drives."""

    model_config = ConfigDict(extra="forbid")

    lat: float
    lon: float
    dc_capacity_mw: float
    tilt_deg: float
    azimuth_deg: float
    losses_pct: float
    tracking: Literal["fixed", "single_axis", "single_axis_backtracked"] = "fixed"

    @field_validator("lat")
    @classmethod
    def _valid_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError(f"lat must be in [-90, 90], got {v}")
        return v

    @field_validator("lon")
    @classmethod
    def _valid_lon(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError(f"lon must be in [-180, 180], got {v}")
        return v

    @field_validator("tilt_deg")
    @classmethod
    def _valid_tilt(cls, v: float) -> float:
        if not 0 <= v <= 90:
            raise ValueError(f"tilt_deg must be in [0, 90], got {v}")
        return v

    @field_validator("azimuth_deg")
    @classmethod
    def _valid_azimuth(cls, v: float) -> float:
        if not 0 <= v < 360:
            raise ValueError(f"azimuth_deg must be in [0, 360), got {v}")
        return v

    @field_validator("losses_pct")
    @classmethod
    def _valid_losses(cls, v: float) -> float:
        if not 0 <= v <= 100:
            raise ValueError(f"losses_pct must be in [0, 100], got {v}")
        return v

    @field_validator("dc_capacity_mw")
    @classmethod
    def _positive_capacity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"dc_capacity_mw must be positive, got {v}")
        return v

    @property
    def array_type(self) -> int:
        """PVWatts array_type code.

        Mounting is a first-class contract input, not a constant: trackers
        push output into the evening, which is exactly the shape question
        this tool exists to answer. Utility-scale single-axis plants almost
        always backtrack to avoid row-to-row shading at low sun angles, so
        prefer single_axis_backtracked over the un-backtracked variant unless
        the plant is known not to.
        """
        return {"fixed": 0, "single_axis": 2, "single_axis_backtracked": 3}[self.tracking]


class StorageSpec(BaseModel):
    """An optional battery paired with the project (Phase 4 storage overlay).

    Modelled as DC-coupled: it charges only from the project's own output,
    which is both the common utility-scale arrangement and what keeps the
    "shift solar out of midday" framing honest -- no grid arbitrage sneaks
    into the capture-rate uplift.
    """

    model_config = ConfigDict(extra="forbid")

    power_mw: float
    duration_hours: float
    round_trip_efficiency: float = 0.85

    @field_validator("power_mw", "duration_hours")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"must be positive, got {v}")
        return v

    @field_validator("round_trip_efficiency")
    @classmethod
    def _valid_efficiency(cls, v: float) -> float:
        if not 0 < v <= 1:
            raise ValueError(f"round_trip_efficiency must be in (0, 1], got {v}")
        return v

    @property
    def energy_capacity_mwh(self) -> float:
        return self.power_mw * self.duration_hours


class Contract(BaseModel):
    """A single VPPA deal, as loaded from a contract YAML file."""

    model_config = ConfigDict(extra="forbid")

    name: str
    counterparty_view: Literal["buyer", "seller"]
    strike_usd_mwh: float
    contract_mw: float
    term: Term
    settlement_index: Literal["hub", "node"]
    hub: str
    node: str
    negative_price_floor: float | None = None
    escalation_pct_yr: float = 0.0
    project: ProjectSpec
    storage: StorageSpec | None = None

    @field_validator("contract_mw")
    @classmethod
    def _positive_contract_mw(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"contract_mw must be positive, got {v}")
        return v

    @property
    def inverter_loading_ratio(self) -> float:
        """DC capacity / contract (AC) capacity. Typical utility-scale range is
        1.25-1.35; document whatever value the project actually uses."""
        return self.project.dc_capacity_mw / self.contract_mw

    @property
    def settlement_point(self) -> str:
        """The price point this contract's output actually settles against."""
        return self.hub if self.settlement_index == "hub" else self.node

    @property
    def counterparty_sign(self) -> int:
        """+1 to report cash flows from the buyer's side, -1 from the seller's.

        settle() always returns cash_to_buyer, which stays the one canonical
        convention; this is what flips it for presentation so a seller-view
        contract doesn't silently show the buyer's P&L.
        """
        return 1 if self.counterparty_view == "buyer" else -1

    def strike_for_year(self, year: int) -> float:
        """The strike escalated to `year`, compounding annually from the first
        year of the term.

        A contract with escalation_pct_yr set would otherwise settle flat for
        its whole term, understating the buyer's obligation in later years.
        """
        elapsed = year - self.term.start.year
        return self.strike_usd_mwh * (1 + self.escalation_pct_yr / 100.0) ** elapsed

    def covers_year(self, year: int) -> bool:
        """Whether `year` falls inside the contract term.

        Settling outside the term is legitimate for counterfactuals (what would
        this deal have done in 2019?), so this reports rather than forbids --
        but callers should say out loud when they are doing it.
        """
        return self.term.start.year <= year <= self.term.end.year


def load_contract(path: str | Path) -> Contract:
    """Load and validate a contract YAML file, e.g. contracts/example_ercot_west.yaml."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return Contract.model_validate(raw)
