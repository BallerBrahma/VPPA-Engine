"""Battery dispatch LP: shift solar out of saturated midday into the peak."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import linprog

from vppa.model import StorageSpec

Foresight = str  # "annual" | "daily"

# ERCOT's day-ahead market clears a *local* operating day. Splitting on UTC
# days instead cuts straight through the evening peak -- 62% of a West Texas
# battery's discharge lands in UTC hours 00-03, which is 18:00-21:00 Central
# the previous afternoon -- and severs the charge-then-discharge cycle the
# daily mode exists to model.
MARKET_TIMEZONE = "America/Chicago"


def _solve_block(
    generation: np.ndarray,
    value: np.ndarray,
    storage: StorageSpec,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """One LP over a contiguous block of hours. Returns charge, discharge, soc,
    curtailed."""
    n = len(generation)
    power = storage.power_mw
    capacity = storage.energy_capacity_mwh
    leg = np.sqrt(storage.round_trip_efficiency)
    cycling = storage.cycling_cost_usd_mwh

    # variables: [c_0..c_n-1, d_0..d_n-1, s_0..s_n-1, x_0..x_n-1]
    # linprog minimises, so revenue terms enter negated. Charging and spilling
    # both reduce exports (+value); discharging raises them (-value) and pays
    # the cycling cost that stands in for degradation.
    objective = np.concatenate([value, -value + cycling, np.zeros(n), value])

    # s_t - s_{t-1} - leg*c_t + d_t/leg = 0, with s_{-1} = 0 (empty at start)
    rows, cols, vals = [], [], []
    for t in range(n):
        rows += [t, t, t]
        cols += [t, n + t, 2 * n + t]
        vals += [-leg, 1.0 / leg, 1.0]
        if t > 0:
            rows.append(t)
            cols.append(2 * n + t - 1)
            vals.append(-1.0)
    balance = sparse.csr_matrix((vals, (rows, cols)), shape=(n, 4 * n))

    # Two inequality blocks, both per hour:
    #   c_t + x_t <= generation_t  -- an hour's output can be stored or
    #     spilled, but not both, and the LP must not spill what it charged.
    #   c_t + d_t <= power         -- one inverter. Without this the LP happily
    #     charges and discharges simultaneously, which is free when cycling
    #     costs nothing: it does not change revenue, but it invents throughput
    #     and inflates the reported cycle count.
    rows, cols, vals = [], [], []
    for t in range(n):
        rows += [t, t]
        cols += [t, 3 * n + t]
        vals += [1.0, 1.0]
    for t in range(n):
        rows += [n + t, n + t]
        cols += [t, n + t]
        vals += [1.0, 1.0]
    limits = sparse.csr_matrix((vals, (rows, cols)), shape=(2 * n, 4 * n))
    limit_rhs = np.concatenate([generation, np.full(n, power)])

    bounds = (
        [(0.0, float(min(power, g))) for g in generation]
        + [(0.0, power)] * n
        + [(0.0, capacity)] * n
        + [(0.0, float(g)) for g in generation]
    )

    result = linprog(
        c=objective,
        A_eq=balance,
        b_eq=np.zeros(n),
        A_ub=limits,
        b_ub=limit_rhs,
        bounds=bounds,
        method="highs",
    )
    if not result.success:
        raise RuntimeError(f"battery dispatch LP did not solve: {result.message}")

    return (
        result.x[:n],
        result.x[n : 2 * n],
        result.x[2 * n : 3 * n],
        result.x[3 * n :],
    )


def dispatch(
    generation_mwh: pd.Series,
    price: pd.Series,
    storage: StorageSpec,
    curtail_below_usd_mwh: float = 0.0,
    foresight: Foresight = "annual",
    market_timezone: str = MARKET_TIMEZONE,
) -> pd.DataFrame:
    """Optimally dispatch a DC-coupled battery against `price`.

    Returns an hourly frame: generation, charge, discharge, soc, curtailed,
    delivered. `delivered` is what leaves the meter
    (generation - charge + discharge - curtailed) and is the series to settle
    on in place of raw generation.

    Formulation. Variables per hour are charge c_t, discharge d_t,
    state-of-charge s_t and curtailment x_t. The only coupling constraint is
    the SOC balance

        s_t - s_{t-1} - sqrt(eff)*c_t + d_t/sqrt(eff) = 0

    which is banded and sparse -- 8,760 hours stays a few seconds of HiGHS.
    Expressing SOC as cumulative sums of c and d instead would make each row
    dense and the problem O(T^2).

    Charging is capped at that hour's own generation, so the battery can never
    buy from the grid: the uplift reported here is genuinely time-shifted
    solar, not arbitrage. Round-trip efficiency is split evenly across the
    charge and discharge legs.

    Curtailment is a decision, not a filter applied afterwards. The battery
    weighs storing an oversupplied hour against spilling it, which is the whole
    question storage is meant to answer -- deciding it outside the LP would
    hand the battery energy a real plant had already thrown away, or throw away
    energy the battery wanted.

    `curtail_below_usd_mwh` is the operator's walk-away price and shifts the
    whole objective: the LP optimises on `price - curtail_below`, the value of
    exporting a megawatt-hour net of whatever incentive keeps the plant running
    at negative prices. Revenue is still reported at market price.

    `foresight` bounds the optimism. "annual" solves all 8,760 hours at once
    and can move energy anywhere in the year -- an upper bound no operator
    achieves. "daily" solves each calendar day independently with the battery
    starting empty, which is close to what a day-ahead bidder actually knows.
    The gap between them is the value of foresight nobody has.
    """
    if not generation_mwh.index.equals(price.index):
        raise ValueError(
            "generation_mwh and price indexes do not match -- align them "
            "before dispatching"
        )
    if foresight not in ("annual", "daily"):
        raise ValueError(f"foresight must be 'annual' or 'daily', got {foresight!r}")

    n = len(generation_mwh)
    if n == 0:
        raise ValueError("cannot dispatch over an empty series")

    generation = generation_mwh.to_numpy(dtype=float)
    value = price.to_numpy(dtype=float) - curtail_below_usd_mwh

    if foresight == "annual":
        charge, discharge, soc, curtailed = _solve_block(generation, value, storage)
    else:
        charge = np.empty(n)
        discharge = np.empty(n)
        soc = np.empty(n)
        curtailed = np.empty(n)
        days = generation_mwh.index.tz_convert(market_timezone).normalize()
        for _, positions in pd.Series(np.arange(n), index=days).groupby(level=0):
            block = positions.to_numpy()
            c, d, s, x = _solve_block(
                generation[block], value[block], storage
            )
            charge[block], discharge[block] = c, d
            soc[block], curtailed[block] = s, x

    return pd.DataFrame(
        {
            "generation": generation,
            "charge": charge,
            "discharge": discharge,
            "soc": soc,
            "curtailed": curtailed,
            "delivered": generation - charge + discharge - curtailed,
        },
        index=generation_mwh.index,
    )


def storage_uplift(
    generation_mwh: pd.Series,
    price: pd.Series,
    storage: StorageSpec,
    curtail_below_usd_mwh: float = 0.0,
    foresight: Foresight = "annual",
    market_timezone: str = MARKET_TIMEZONE,
) -> dict[str, float]:
    """Capture-rate and revenue uplift from adding the battery.

    Compares settling on raw generation against settling on the battery's
    delivered profile, holding prices fixed. Round-trip losses mean delivered
    volume is strictly lower than generation -- the uplift has to come from
    price capture, which is exactly the claim being tested.
    """
    from vppa.engine.metrics import capture_rate

    dispatched = dispatch(
        generation_mwh,
        price,
        storage,
        curtail_below_usd_mwh=curtail_below_usd_mwh,
        foresight=foresight,
        market_timezone=market_timezone,
    )
    delivered = dispatched["delivered"]

    base_revenue = float((generation_mwh * price).sum())
    uplift_revenue = float((delivered * price).sum())
    throughput = float(dispatched["discharge"].sum())

    return {
        "generation_mwh": float(generation_mwh.sum()),
        "delivered_mwh": float(delivered.sum()),
        "curtailed_mwh": float(dispatched["curtailed"].sum()),
        "round_trip_loss_mwh": float(
            generation_mwh.sum()
            - dispatched["curtailed"].sum()
            - delivered.sum()
        ),
        "capture_rate_base": capture_rate(generation_mwh, price),
        "capture_rate_with_storage": capture_rate(delivered, price),
        "revenue_base_usd": base_revenue,
        "revenue_with_storage_usd": uplift_revenue,
        "revenue_uplift_usd": uplift_revenue - base_revenue,
        "cycling_cost_usd": throughput * storage.cycling_cost_usd_mwh,
        "cycles": float(dispatched["charge"].sum() / storage.energy_capacity_mwh),
    }


def foresight_premium(
    generation_mwh: pd.Series,
    price: pd.Series,
    storage: StorageSpec,
    curtail_below_usd_mwh: float = 0.0,
    market_timezone: str = MARKET_TIMEZONE,
) -> dict[str, float]:
    """How much of the battery's uplift depends on knowing the whole year.

    The annual LP is an upper bound nobody reaches. Solving each day on its own
    is a far better stand-in for a day-ahead bidder, who genuinely does know
    the next 24 hours of prices. The difference is the premium the headline
    number is carrying.
    """
    perfect = storage_uplift(
        generation_mwh,
        price,
        storage,
        curtail_below_usd_mwh,
        foresight="annual",
        market_timezone=market_timezone,
    )
    daily = storage_uplift(
        generation_mwh,
        price,
        storage,
        curtail_below_usd_mwh,
        foresight="daily",
        market_timezone=market_timezone,
    )
    return {
        "revenue_uplift_perfect_usd": perfect["revenue_uplift_usd"],
        "revenue_uplift_daily_usd": daily["revenue_uplift_usd"],
        "foresight_premium_usd": perfect["revenue_uplift_usd"]
        - daily["revenue_uplift_usd"],
        "capture_rate_perfect": perfect["capture_rate_with_storage"],
        "capture_rate_daily": daily["capture_rate_with_storage"],
    }
