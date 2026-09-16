"""ERCOT settlement-point registry: which nodes actually exist.

A contract can name any string as its node, and the failure mode without this
is bad: the analysis runs, hits the nodal price API, and comes back empty
several seconds later with "check the settlement point name". That is a
question we can answer before spending anything, so this pulls ERCOT's own
resource-node list and caches it.

Both source reports come from ERCOT's public MIS, not the metered gridstatus.io
API, so refreshing the registry costs nothing but time.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from vppa import store

# The registry is a snapshot of ERCOT's current network model, not a per-year
# fact, so it is cached under the year it was pulled.
REGISTRY_SOURCE = "settlement_points"
REGISTRY_KEY = "ercot"


def fetch_settlement_points(refresh: bool = False) -> pd.DataFrame:
    """Every ERCOT resource node, with its load zone and substation.

    Columns: node, zone, substation. Cached indefinitely -- new solar nodes
    appear as plants energize, so pass refresh=True to pull a fresh snapshot
    into the current year's partition.
    """
    year = dt.datetime.now(tz=dt.UTC).year
    if not refresh:
        for candidate in range(year, year - 5, -1):
            cached = store.read_frame(
                source=REGISTRY_SOURCE, key=REGISTRY_KEY, year=candidate
            )
            if cached is not None:
                return cached

    from gridstatus import Ercot

    ercot = Ercot()
    nodes = ercot.get_resource_node_to_unit(date="latest")
    buses = ercot.get_settlement_points_electrical_bus_mapping(date="latest")

    zones = (
        buses.dropna(subset=["Resource Node"])
        .groupby("Resource Node")
        .agg(zone=("Settlement Load Zone", "first"), substation=("Substation", "first"))
    )
    registry = (
        nodes[["Resource Node"]]
        .drop_duplicates()
        .rename(columns={"Resource Node": "node"})
        .join(zones, on="node")
        .sort_values("node")
        .reset_index(drop=True)
    )

    try:
        store.write_frame(registry, source=REGISTRY_SOURCE, key=REGISTRY_KEY, year=year)
    except FileExistsError:
        pass  # refresh=True against today's partition; the fetch still stands
    return registry


# Remembers a failed pull for the life of the process. Success is already
# cached to Parquet; without this, an offline machine pays a fresh connection
# timeout on every page load, since the API consults the registry on both the
# contract list and the availability check.
_UNAVAILABLE = False


def known_nodes(refresh: bool = False) -> set[str]:
    """Valid ERCOT resource-node names, or an empty set if the registry cannot
    be reached.

    Empty means "no claim", not "no nodes": callers must treat it as permissive,
    because refusing every node on a machine that simply has not pulled the
    list yet would be worse than the error this exists to prevent.
    """
    global _UNAVAILABLE
    if _UNAVAILABLE and not refresh:
        return set()
    try:
        nodes = set(fetch_settlement_points(refresh=refresh)["node"])
    except Exception:  # noqa: BLE001 -- any ingest failure means "no claim"
        _UNAVAILABLE = True
        return set()
    _UNAVAILABLE = False
    return nodes
