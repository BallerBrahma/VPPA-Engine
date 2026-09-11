"""Read/write immutable Parquet cache, partitioned by source / iso / year."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")


def cache_path(source: str, key: str, year: int) -> Path:
    return DATA_DIR / source / key / f"{year}.parquet"


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
