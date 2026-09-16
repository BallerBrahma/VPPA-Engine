import pandas as pd
import pytest

from vppa.align import align_price_to_generation


def _utc(start, periods):
    return pd.date_range(start, periods=periods, freq="h", tz="UTC")


def test_identical_indexes_pass_through():
    idx = _utc("2024-06-01", 5)
    gen = pd.Series(1.0, index=idx)
    price = pd.Series(20.0, index=idx)

    assert align_price_to_generation(gen, price)[0] is price


def test_drops_price_hours_generation_cannot_represent():
    gen_idx = _utc("2024-06-01", 5)
    # price carries two extra hours the TMY calendar has no counterpart for
    price_idx = _utc("2024-06-01", 7)
    gen = pd.Series(1.0, index=gen_idx)
    price = pd.Series(range(7), index=price_idx, dtype=float)

    aligned = align_price_to_generation(gen, price)[0]

    assert aligned.index.equals(gen_idx)
    assert aligned.tolist() == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_raises_when_generation_has_hours_price_lacks():
    gen = pd.Series(1.0, index=_utc("2024-06-01", 6))
    price = pd.Series(1.0, index=_utc("2024-06-01", 4))

    with pytest.raises(ValueError, match="no matching price data"):
        align_price_to_generation(gen, price)[0]


def test_raises_when_indexes_merely_overlap():
    # same length, but offset -- dropping extras can never reconcile these,
    # and silently settling them would pair mismatched hours
    gen = pd.Series(1.0, index=_utc("2024-06-01T00:00:00", 5))
    price = pd.Series(1.0, index=_utc("2024-06-01T03:00:00", 5))

    with pytest.raises(ValueError, match="no matching price data"):
        align_price_to_generation(gen, price)[0]
