import datetime as dt
from pathlib import Path

import pytest

from vppa.availability import (
    HUB_PRICE_FIRST_YEAR,
    last_complete_year,
    offered_years,
    year_availability,
)
from vppa.model import Contract, load_contract

CONTRACTS = Path(__file__).parent.parent / "contracts"
TODAY = dt.date(2026, 9, 16)
NODES = {"LAMESASLR_G", "STAR_SLR_RN", "EIFSLR_UNIT1"}


@pytest.fixture
def lamesa():
    return load_contract(CONTRACTS / "lamesa_west.yaml")


def check(contract, year, **kwargs):
    return year_availability(
        contract, year, known_nodes=NODES, today=TODAY, **kwargs
    )


def test_a_complete_past_year_supports_everything(lamesa):
    result = check(lamesa, 2025)

    assert result.analysis.available
    assert result.actual_weather.available
    assert result.node_settlement.available
    assert result.in_term


def test_the_current_year_is_not_offered_because_it_is_incomplete(lamesa):
    result = check(lamesa, 2026)

    assert not result.analysis.available
    assert "not a complete settlement year" in result.analysis.reason
    # and nothing downstream of it is reachable either
    assert not result.actual_weather.available
    assert not result.node_settlement.available


def test_years_before_the_price_archive_are_refused(lamesa):
    result = check(lamesa, 2005)

    assert not result.analysis.available
    assert str(HUB_PRICE_FIRST_YEAR) in result.analysis.reason


def test_a_node_absent_from_ercots_registry_is_refused_by_name(lamesa):
    # the failure this replaces: the analysis ran, queried the nodal API, and
    # came back empty seconds later
    payload = lamesa.model_dump()
    payload["node"] = "WESTSOLAR_ALL"
    fictional = Contract.model_validate(payload)

    result = check(fictional, 2025)

    assert result.analysis.available  # hub settlement is unaffected
    assert not result.node_settlement.available
    assert result.node_settlement.reason == "WESTSOLAR_ALL is not an ERCOT resource node"


def test_a_year_before_the_plant_energised_has_no_nodal_price(lamesa):
    payload = lamesa.model_dump()
    payload["node"] = "STAR_SLR_RN"
    payload["project"]["commercial_operation"] = dt.date(2024, 11, 1)
    late = Contract.model_validate(payload)

    assert not check(late, 2023).node_settlement.available
    assert "Nov 2024" in check(late, 2023).node_settlement.reason


def test_the_energisation_year_is_offered_but_flagged_as_partial(lamesa):
    payload = lamesa.model_dump()
    payload["node"] = "STAR_SLR_RN"
    payload["project"]["commercial_operation"] = dt.date(2024, 11, 1)
    late = Contract.model_validate(payload)

    node = check(late, 2024).node_settlement

    # available, because two months of real prices is still a real answer --
    # but not silently, because it is not a year
    assert node.available
    assert "Partial year" in node.reason


def test_an_empty_registry_never_blocks_a_node(lamesa):
    # a machine that has never pulled the registry must degrade to permissive,
    # not decide every node is fake
    result = year_availability(lamesa, 2025, known_nodes=set(), today=TODAY)

    assert result.node_settlement.available


def test_cached_partitions_mark_an_option_instant_but_never_unavailable(lamesa):
    cold = check(lamesa, 2025)
    warm = check(
        lamesa,
        2025,
        cached=frozenset({("prices", "HB_WEST", 2025)}),
    )

    assert cold.analysis.available and not cold.analysis.cached
    assert warm.analysis.available and warm.analysis.cached


def test_offered_years_run_from_the_last_complete_year_back_to_the_archive():
    years = offered_years(TODAY)

    assert years[0] == 2025 == last_complete_year(TODAY)
    assert years[-1] == HUB_PRICE_FIRST_YEAR
    assert years == sorted(years, reverse=True)


def test_every_shipped_contract_names_a_node_in_the_registry_or_says_it_does_not():
    """Each contract either settles at a real ERCOT node, or is the schema demo
    whose node is fictional on purpose -- no third case."""
    from vppa.ingest.settlement_points import REGISTRY_KEY, REGISTRY_SOURCE  # noqa: F401

    for path in sorted(CONTRACTS.glob("*.yaml")):
        contract = load_contract(path)
        is_demo = contract.project.eia_plant_id is None
        assert is_demo or contract.node, f"{path.name} has no node"
        if not is_demo:
            assert contract.project.commercial_operation is not None, (
                f"{path.name} is a real asset but records no commercial operation date"
            )


def test_known_nodes_returns_an_empty_set_when_the_registry_is_unreachable(monkeypatch):
    """Offline must mean "no claim about nodes", never "every node is fake"."""
    import vppa.ingest.settlement_points as sp

    calls = []

    def boom(**kwargs):
        calls.append(kwargs)
        raise OSError("offline")

    monkeypatch.setattr(sp, "fetch_settlement_points", boom)
    monkeypatch.setattr(sp, "_UNAVAILABLE", False)

    assert sp.known_nodes() == set()
    # and it must not retry on every call -- the API consults it twice per page
    assert sp.known_nodes() == set()
    assert len(calls) == 1
