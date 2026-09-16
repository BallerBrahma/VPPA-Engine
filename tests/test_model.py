from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from vppa.model import Contract, GenerationProfile, PriceSeries, load_contract

EXAMPLE_CONTRACT = Path(__file__).parent.parent / "contracts" / "example_ercot_west.yaml"


def test_load_contract_example():
    contract = load_contract(EXAMPLE_CONTRACT)

    assert contract.name == "ercot_west_solar_150mw"
    assert contract.strike_usd_mwh == pytest.approx(34.50)
    assert contract.settlement_index == "hub"
    assert contract.settlement_point == "HB_WEST"
    assert contract.inverter_loading_ratio == pytest.approx(195 / 150)


def test_contract_rejects_unknown_field(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(EXAMPLE_CONTRACT.read_text() + "\nunexpected_field: 1\n")

    with pytest.raises(ValidationError):
        load_contract(bad)


def test_contract_rejects_end_before_start(tmp_path):
    bad = tmp_path / "bad.yaml"
    text = EXAMPLE_CONTRACT.read_text().replace(
        "term: {start: 2023-01-01, end: 2025-12-31}",
        "term: {start: 2025-12-31, end: 2023-01-01}",
    )
    bad.write_text(text)

    with pytest.raises(ValidationError, match="must be after"):
        load_contract(bad)


def test_project_spec_rejects_out_of_range_tilt(tmp_path):
    bad = tmp_path / "bad.yaml"
    text = EXAMPLE_CONTRACT.read_text().replace("tilt_deg: 25", "tilt_deg: 190")
    bad.write_text(text)

    with pytest.raises(ValidationError, match="tilt_deg"):
        load_contract(bad)


def test_price_series_rejects_naive_timestamps():
    naive_index = pd.date_range("2024-01-01", periods=3, freq="h")
    series = pd.Series([10.0, 20.0, 30.0], index=naive_index)

    with pytest.raises(ValidationError, match="tz-aware UTC"):
        PriceSeries(settlement_point="HB_WEST", series=series)


def test_price_series_rejects_dst_duplicate_hour():
    # the classic fall-back trap: 1:00 AM Central occurs twice in November
    index = pd.to_datetime(
        ["2024-11-03T06:00:00Z", "2024-11-03T07:00:00Z", "2024-11-03T07:00:00Z"]
    )
    series = pd.Series([10.0, 20.0, 20.0], index=index)

    with pytest.raises(ValidationError, match="duplicate timestamps"):
        PriceSeries(settlement_point="HB_WEST", series=series)


def test_generation_profile_rejects_negative_values():
    index = pd.date_range("2024-06-01", periods=3, freq="h", tz="UTC")
    series = pd.Series([0.0, -5.0, 100.0], index=index)

    with pytest.raises(ValidationError, match="must not contain negative values"):
        GenerationProfile(project_name="test_project", series=series)


def test_contract_is_immutable_construction_from_dict_roundtrip():
    contract = load_contract(EXAMPLE_CONTRACT)
    assert Contract.model_validate(contract.model_dump()) == contract


def test_strike_escalates_from_the_first_year_of_the_term(tmp_path):
    text = EXAMPLE_CONTRACT.read_text().replace(
        "escalation_pct_yr: 0.0", "escalation_pct_yr: 2.5"
    )
    path = tmp_path / "esc.yaml"
    path.write_text(text)
    contract = load_contract(path)

    assert contract.strike_for_year(2023) == pytest.approx(34.50)
    assert contract.strike_for_year(2024) == pytest.approx(34.50 * 1.025)
    assert contract.strike_for_year(2025) == pytest.approx(34.50 * 1.025**2)


def test_zero_escalation_leaves_the_strike_flat(example_contract):
    assert example_contract.strike_for_year(2025) == pytest.approx(
        example_contract.strike_usd_mwh
    )


def test_counterparty_sign_flips_for_a_seller_view(tmp_path, example_contract):
    assert example_contract.counterparty_sign == 1

    text = EXAMPLE_CONTRACT.read_text().replace(
        "counterparty_view: buyer", "counterparty_view: seller"
    )
    path = tmp_path / "seller.yaml"
    path.write_text(text)

    assert load_contract(path).counterparty_sign == -1


def test_covers_year_bounds_the_term(example_contract):
    assert example_contract.covers_year(2023)
    assert example_contract.covers_year(2025)
    assert not example_contract.covers_year(2019)
    assert not example_contract.covers_year(2026)


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "../../../../tmp/evil"),
        ("name", "has spaces"),
        ("hub", "../HB_WEST"),
        ("node", "nodes/LAMESASLR_G"),
        ("name", ""),
    ],
)
def test_contract_rejects_names_that_would_escape_the_cache(
    example_contract, field, value
):
    """These land in cache directory paths, and manual entry in the UI makes
    every one of them user-supplied."""
    payload = example_contract.model_dump()
    payload[field] = value

    with pytest.raises(ValidationError):
        Contract.model_validate(payload)


def test_a_contract_may_name_no_node_at_all(example_contract):
    payload = example_contract.model_dump()
    payload["node"] = ""

    assert Contract.model_validate(payload).node == ""
