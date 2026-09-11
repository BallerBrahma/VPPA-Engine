"""Battery dispatch LP: shift solar out of saturated midday into the peak."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import linprog

from vppa.model import StorageSpec


def dispatch(
    generation_mwh: pd.Series,
    price: pd.Series,
    storage: StorageSpec,
) -> pd.DataFrame:
    """Optimally dispatch a DC-coupled battery against `price`.

    Returns an hourly frame: generation, charge, discharge, soc, delivered.
    `delivered` is what leaves the meter (generation - charge + discharge) and
    is the series to settle on in place of raw generation.

    Formulation. Variables per hour are charge c_t, discharge d_t and
    state-of-charge s_t, so the only coupling constraint is the SOC balance

        s_t - s_{t-1} - sqrt(eff)*c_t + d_t/sqrt(eff) = 0

    which is banded and sparse -- 8,760 hours stays a few seconds of HiGHS.
    Expressing SOC as cumulative sums of c and d instead would make each row
    dense and the problem O(T^2).

    The objective maximises revenue, sum(price * delivered). The generation
    term is a constant, so the LP only sees sum(price * (d_t - c_t)).

    Charging is capped at that hour's own generation, so the battery can never
    buy from the grid: the uplift reported here is genuinely time-shifted
    solar, not arbitrage. Round-trip efficiency is split evenly across the
    charge and discharge legs.
    """
    if not generation_mwh.index.equals(price.index):
        raise ValueError(
            "generation_mwh and price indexes do not match -- align them "
            "before dispatching"
        )

    n = len(generation_mwh)
    if n == 0:
        raise ValueError("cannot dispatch over an empty series")

    power = storage.power_mw
    capacity = storage.energy_capacity_mwh
    leg = np.sqrt(storage.round_trip_efficiency)

    generation = generation_mwh.to_numpy(dtype=float)
    prices = price.to_numpy(dtype=float)

    # variables: [c_0..c_n-1, d_0..d_n-1, s_0..s_n-1]
    objective = np.concatenate([prices, -prices, np.zeros(n)])

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
    balance = sparse.csr_matrix((vals, (rows, cols)), shape=(n, 3 * n))

    bounds = (
        # charge is capped by this hour's own output as well as by power
        [(0.0, float(min(power, g))) for g in generation]
        + [(0.0, power)] * n
        + [(0.0, capacity)] * n
    )

    result = linprog(
        c=objective,
        A_eq=balance,
        b_eq=np.zeros(n),
        bounds=bounds,
        method="highs",
    )
    if not result.success:
        raise RuntimeError(f"battery dispatch LP did not solve: {result.message}")

    charge = result.x[:n]
    discharge = result.x[n : 2 * n]
    soc = result.x[2 * n :]

    return pd.DataFrame(
        {
            "generation": generation,
            "charge": charge,
            "discharge": discharge,
            "soc": soc,
            "delivered": generation - charge + discharge,
        },
        index=generation_mwh.index,
    )


def storage_uplift(
    generation_mwh: pd.Series,
    price: pd.Series,
    storage: StorageSpec,
) -> dict[str, float]:
    """Capture-rate and revenue uplift from adding the battery.

    Compares settling on raw generation against settling on the battery's
    delivered profile, holding prices fixed. Round-trip losses mean delivered
    volume is strictly lower than generation -- the uplift has to come from
    price capture, which is exactly the claim being tested.
    """
    from vppa.engine.metrics import capture_rate

    dispatched = dispatch(generation_mwh, price, storage)
    delivered = dispatched["delivered"]

    base_revenue = float((generation_mwh * price).sum())
    uplift_revenue = float((delivered * price).sum())

    return {
        "generation_mwh": float(generation_mwh.sum()),
        "delivered_mwh": float(delivered.sum()),
        "round_trip_loss_mwh": float(generation_mwh.sum() - delivered.sum()),
        "capture_rate_base": capture_rate(generation_mwh, price),
        "capture_rate_with_storage": capture_rate(delivered, price),
        "revenue_base_usd": base_revenue,
        "revenue_with_storage_usd": uplift_revenue,
        "revenue_uplift_usd": uplift_revenue - base_revenue,
        "cycles": float(dispatched["charge"].sum() / storage.energy_capacity_mwh),
    }
