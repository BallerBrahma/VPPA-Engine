"""matplotlib (static) + plotly (interactive) chart builders."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # README figures are rendered headless, never shown
import matplotlib.pyplot as plt
import pandas as pd

SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
SERIES_1 = "#2a78d6"
GRID = "#e5e4e0"


def capture_rate_decay(
    frame: pd.DataFrame,
    path: str | Path,
    capacity_column: str = "ercot_solar_mw",
    capacity_label: str = "ERCOT installed solar (GW)",
) -> Path:
    """Capture rate against solar penetration, one point per year.

    Deliberately a connected scatter rather than two lines on twin axes: a
    dual-axis plot of "% on the left, MW on the right" invites the reader to
    read a crossing point that means nothing, and the relationship is the
    actual finding. Putting penetration on x and capture rate on y shows that
    relationship directly, while connecting the points in year order keeps the
    time dimension visible without a second scale.

    `frame` is indexed by year with a `capture_rate` column (as a ratio) and a
    capacity column in MW.
    """
    frame = frame.sort_index()
    x = frame[capacity_column] / 1000.0  # MW -> GW, to keep the axis readable
    y = frame["capture_rate"] * 100.0

    fig, ax = plt.subplots(figsize=(8, 5), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    # 100% = the asset captures exactly the average market price. Above it
    # solar earns a premium, below it a discount -- the line the finding crosses.
    ax.axhline(100, color=TEXT_SECONDARY, linewidth=1, linestyle=(0, (4, 4)), alpha=0.6)
    ax.annotate(
        "100% = captures the average market price",
        xy=(x.max(), 100),
        xytext=(0, 6),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=TEXT_SECONDARY,
    )

    ax.plot(x, y, color=SERIES_1, linewidth=2, zorder=2, alpha=0.55)
    ax.scatter(
        x, y, s=90, color=SERIES_1, zorder=3, edgecolor=SURFACE, linewidth=2
    )

    for year, xi, yi in zip(frame.index, x, y):
        ax.annotate(
            str(year),
            xy=(xi, yi),
            xytext=(0, 11),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color=TEXT_PRIMARY,
        )

    ax.set_xlabel(capacity_label, fontsize=10, color=TEXT_SECONDARY)
    ax.set_ylabel("Capture rate (%)", fontsize=10, color=TEXT_SECONDARY)
    ax.set_title(
        "Solar capture rate falls as ERCOT solar builds out",
        fontsize=13,
        color=TEXT_PRIMARY,
        pad=14,
        loc="left",
    )

    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9)

    # headroom so the year labels above the topmost point aren't clipped
    ax.set_ylim(min(50, y.min() - 10), y.max() + 18)

    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path
