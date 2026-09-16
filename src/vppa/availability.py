"""What can actually be run, decided before anything is fetched.

The UI used to offer every year, both weather bases and node settlement for
every contract, and you found out which combinations had no data behind them by
running the analysis and reading the traceback. These are answerable up front:
ERCOT publishes its resource-node list, NSRDB publishes on a known lag, and a
plant has no nodal price before it energises.

The rules live here as pure functions over injected facts -- the node registry
and the set of cached partitions are passed in, never fetched -- so they are
testable offline and the API layer stays the only thing doing I/O.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from vppa.ingest.generation import cache_key
from vppa.model import Contract

# ERCOT's day-ahead SPP archive. gridstatus exposes it back through 2011.
HUB_PRICE_FIRST_YEAR = 2011

# NSRDB's earliest GOES year. The late bound is a publication lag, not a fixed
# year: a given year's aggregated file lands partway through the next one.
NSRDB_FIRST_YEAR = 1998


def last_complete_year(today: dt.date | None = None) -> int:
    """The most recent year that has a full 8,760 hours of settled prices.

    Annual capture rates and cash totals are only comparable over whole years,
    so a year still in progress is not offered.
    """
    today = today or dt.datetime.now(tz=dt.UTC).date()
    return today.year - 1


@dataclass(frozen=True)
class Option:
    """One toggle in the UI, and whether it can be turned on."""

    available: bool
    cached: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class YearAvailability:
    year: int
    in_term: bool
    analysis: Option
    actual_weather: Option
    node_settlement: Option


def _month_name(date: dt.date) -> str:
    return date.strftime("%b %Y")


def year_availability(
    contract: Contract,
    year: int,
    *,
    known_nodes: set[str],
    cached: frozenset[tuple[str, str, int]] = frozenset(),
    today: dt.date | None = None,
) -> YearAvailability:
    """Decide what `contract` supports in `year`.

    `known_nodes` is ERCOT's resource-node list. `cached` is a set of
    (source, key, year) partitions already on disk, used only to mark an
    option as instant -- never to mark one unavailable, since an uncached
    option is merely slower, not impossible.
    """
    latest = last_complete_year(today)

    if year < HUB_PRICE_FIRST_YEAR:
        analysis = Option(False, reason=f"ERCOT price history starts in {HUB_PRICE_FIRST_YEAR}")
    elif year > latest:
        analysis = Option(False, reason=f"{year} is not a complete settlement year yet")
    else:
        analysis = Option(True, cached=("prices", contract.hub, year) in cached)

    if year > latest:
        actual = Option(False, reason=f"NSRDB has not published {year} weather yet")
    elif year < NSRDB_FIRST_YEAR:
        actual = Option(False, reason=f"NSRDB weather starts in {NSRDB_FIRST_YEAR}")
    else:
        actual = Option(True, cached=("generation_actual", cache_key(contract), year) in cached)

    node = _node_option(contract, year, known_nodes=known_nodes, cached=cached)
    if not analysis.available:
        # nothing runs this year, so neither sub-option is reachable
        actual = Option(False, reason=actual.reason or analysis.reason)
        node = Option(False, reason=node.reason or analysis.reason)

    return YearAvailability(
        year=year,
        in_term=contract.covers_year(year),
        analysis=analysis,
        actual_weather=actual,
        node_settlement=node,
    )


def _node_option(
    contract: Contract,
    year: int,
    *,
    known_nodes: set[str],
    cached: frozenset[tuple[str, str, int]],
) -> Option:
    if not contract.node:
        return Option(False, reason="This contract names no project node")
    if known_nodes and contract.node not in known_nodes:
        return Option(
            False,
            reason=f"{contract.node} is not an ERCOT resource node",
        )

    online = contract.project.commercial_operation
    if online is not None and year < online.year:
        return Option(
            False,
            reason=f"The plant reached commercial operation in {_month_name(online)}",
        )
    if online is not None and year == online.year:
        return Option(
            True,
            cached=("prices_gsio", contract.node, year) in cached,
            reason=f"Partial year -- the plant energised in {_month_name(online)}",
        )
    return Option(True, cached=("prices_gsio", contract.node, year) in cached)


def offered_years(today: dt.date | None = None) -> list[int]:
    """Years the picker should list at all, newest first."""
    return list(range(last_complete_year(today), HUB_PRICE_FIRST_YEAR - 1, -1))
