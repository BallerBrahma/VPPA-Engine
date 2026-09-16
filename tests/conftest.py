import os
import socket
from pathlib import Path

import pandas as pd
import pytest

from vppa.model import load_contract

# Importing gridstatusio calls PyPI at import time; tests that patch its client
# pay for that even though they never make a real query. Set before any test
# imports it.
os.environ.setdefault("GSIO_SKIP_VERSION_CHECK", "true")

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


@pytest.fixture(autouse=True)
def no_network():
    """The suite is offline by construction, so make that enforceable.

    Real network behaviour is verified by hand instead (see CLAUDE.md). A test
    that reaches for a socket has either lost its stub or picked up an
    import-time side effect, and both should fail loudly here rather than turn
    into a slow, weather-dependent CI job.
    """
    def deny(*args, **kwargs):
        raise AssertionError(
            "a test tried to open a network connection -- stub the client, or "
            "move the check to a manual run"
        )

    original_connect = socket.socket.connect
    original_create = socket.create_connection
    socket.socket.connect = deny
    socket.create_connection = deny
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create
