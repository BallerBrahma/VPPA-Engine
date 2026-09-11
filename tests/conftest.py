from pathlib import Path

import pandas as pd
import pytest

from vppa.model import load_contract

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE_CONTRACT_PATH = Path(__file__).parent.parent / "contracts" / "example_ercot_west.yaml"


@pytest.fixture
def basic_series():
    """Tiny hand-built hourly (generation_mwh, index_price) pair.

    Deliberately adversarial: the two hours with the most generation carry the
    lowest (and negative) prices, while the day's highest price coincides with
    zero output -- exercising the thesis directly rather than a realistic mix.
    """
    df = pd.read_csv(FIXTURES / "settlement_basic.csv", parse_dates=["timestamp"])
    df = df.set_index("timestamp")
    return df["generation_mwh"], df["index_price"]


@pytest.fixture
def example_contract():
    return load_contract(EXAMPLE_CONTRACT_PATH)


@pytest.fixture
def basis_series():
    """Tiny hand-built (generation_mwh, hub_price, node_price) triple.

    Basis is most negative in the two high-generation midday hours and turns
    positive only in the evening hour the plant is dark -- the locational
    version of the same pattern the settlement fixture exercises.
    """
    df = pd.read_csv(FIXTURES / "basis_basic.csv", parse_dates=["timestamp"])
    df = df.set_index("timestamp")
    return df["generation_mwh"], df["hub_price"], df["node_price"]
