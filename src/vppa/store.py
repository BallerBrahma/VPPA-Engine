"""Read/write immutable Parquet cache, partitioned by source / iso / year."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# Anchored to the repo root rather than the cwd. A relative "data" meant the
# API server, a notebook or a script launched from anywhere but the root would
# quietly start a second, empty cache and re-download everything into it.
# src/vppa/store.py -> src/vppa -> src -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("VPPA_DATA_DIR", _REPO_ROOT / "data"))


def _safe_component(value: str, label: str) -> str:
    """Reject anything that would not be a single directory name.

    `key` is caller-supplied all the way from a contract body -- the contract
    name, a hub, a node -- so this is the boundary where a hand-typed or posted
    value stops being text and becomes a filesystem path. Without it,
    name="../../.." writes the cache outside the data directory entirely.
    """
    if not value or value in (".", "..") or value.startswith("."):
        raise ValueError(f"{label} must be a non-empty name, got {value!r}")
    if "/" in value or "\\" in value or "\0" in value:
        raise ValueError(f"{label} must not contain a path separator, got {value!r}")
    return value


def cache_path(source: str, key: str, year: int) -> Path:
    """Path for one cached partition, guaranteed to sit under DATA_DIR."""
    _safe_component(source, "cache source")
    _safe_component(key, "cache key")

    path = DATA_DIR / source / key / f"{year}.parquet"

    # Belt and braces: the component check above should make this unreachable,
    # but the cost of being wrong is a write outside the project, so confirm
    # the resolved path really is contained before handing it back.
    root = DATA_DIR.resolve()
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"refusing a cache path outside {root}: {path}")
    return path


def write_series(series: pd.Series, source: str, key: str, year: int) -> Path:
    """Write a UTC-indexed series to the Parquet cache.

    Refuses to overwrite an existing partition: the cache is never mutated,
    only ever written once per (source, key, year).
    """
    path = cache_path(source, key, year)
    if path.exists():
        raise FileExistsError(f"{path} already exists -- the Parquet cache is never mutated")
    path.parent.mkdir(parents=True, exist_ok=True)
    series.rename("value").to_frame().to_parquet(path)
    return path


def read_series(source: str, key: str, year: int) -> pd.Series | None:
    """Read a cached series, or None if this partition hasn't been fetched yet."""
    path = cache_path(source, key, year)
    if not path.exists():
        return None
    return pd.read_parquet(path)["value"]


def write_frame(frame: pd.DataFrame, source: str, key: str, year: int) -> Path:
    """Write a DataFrame to the Parquet cache, under the same never-mutated
    rules as write_series (for reference data that isn't a single series --
    generator fleets, settlement point maps)."""
    path = cache_path(source, key, year)
    if path.exists():
        raise FileExistsError(f"{path} already exists -- the Parquet cache is never mutated")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    return path


def read_frame(source: str, key: str, year: int) -> pd.DataFrame | None:
    """Read a cached DataFrame, or None if this partition hasn't been fetched yet."""
    path = cache_path(source, key, year)
    if not path.exists():
        return None
    return pd.read_parquet(path)


def cached_partitions() -> frozenset[tuple[str, str, int]]:
    """Every (source, key, year) already on disk.

    Used to tell a fetch that will be instant from one that will take a
    network round trip -- never to decide whether something is *possible*.
    """
    found = set()
    if not DATA_DIR.is_dir():
        return frozenset()
    for path in DATA_DIR.glob("*/*/*.parquet"):
        if path.stem.isdigit():
            found.add((path.parent.parent.name, path.parent.name, int(path.stem)))
    return frozenset(found)
