import pandas as pd
import pytest
from fastapi.testclient import TestClient

from vppa.api.main import app
from vppa.model import GenerationProfile, PriceSeries

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_registry_network(monkeypatch):
    """Stub ERCOT's settlement-point registry for every test in this module.

    /api/contracts and /api/availability both consult it, and on a machine with
    no cached copy (CI) that is a live call to ercot.com. Both call sites
    already degrade gracefully, but the degradation costs a network timeout
    first, which is not something the suite should ever wait on.
    """
    nodes = {"HB_WEST", "LAMESASLR_G", "NOBLESLR_ALL", "SUNVASLR_ALL",
             "EIFSLR_UNIT1", "FIVEWSLR_ALL", "ZIER_SLR_ALL", "STAR_SLR_RN"}
    monkeypatch.setattr("vppa.api.main.known_nodes", lambda *a, **k: nodes)
    monkeypatch.setattr(
        "vppa.api.main.fetch_settlement_points",
        lambda *a, **k: pd.DataFrame(
            {"node": sorted(nodes), "zone": ["LZ_WEST"] * len(nodes),
             "substation": [""] * len(nodes)}
        ),
    )


@pytest.fixture
def offline(monkeypatch):
    """Patch ingest so the API is exercised without network or API keys."""
    def series_for(year: int):
        """Synthetic hourly data for whichever year is requested -- the API
        filters to the requested year, so a fixed-year fixture would hand back
        an empty series for counterfactual runs."""
        index = pd.date_range(f"{year}-01-01", periods=1500, freq="h", tz="UTC")
        generation = pd.Series(
            [max(0.0, 60.0 - abs(h - 13) * 9) for h in index.hour], index=index
        )
        hub = pd.Series([25.0 + (h - 12) * 3 for h in index.hour], index=index)
        return generation, hub, hub - 6.0

    # patch the names bound inside vppa.api.main, not their source modules:
    # app.py does `from ... import fetch_...` at import time, so rebinding the
    # source module would leave the API calling the real, networked functions
    monkeypatch.setattr(
        "vppa.api.main.fetch_pvwatts_generation",
        lambda contract, year, weather="tmy": GenerationProfile(
            project_name=contract.name, series=series_for(year)[0]
        ),
    )
    monkeypatch.setattr(
        "vppa.api.main.fetch_ercot_hub_dam_prices",
        lambda location, year: PriceSeries(
            settlement_point=location, series=series_for(year)[1]
        ),
    )
    monkeypatch.setattr(
        "vppa.api.main.fetch_ercot_dam_prices",
        lambda location, year: PriceSeries(
            settlement_point=location, series=series_for(year)[2]
        ),
    )


def _request(contract, **kwargs):
    body = {"contract": contract, "year": 2025}
    body.update(kwargs)
    return body


@pytest.fixture
def contract():
    contracts = client.get("/api/contracts").json()
    return next(c["contract"] for c in contracts if c["file"] == "lamesa_west.yaml")


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_list_contracts_returns_repo_contracts():
    body = client.get("/api/contracts").json()

    files = [c["file"] for c in body]
    assert "lamesa_west.yaml" in files
    assert body[0]["contract"]["name"]


def test_settlement_returns_metrics_and_twelve_months(offline, contract):
    response = client.post("/api/settlement", json=_request(contract))

    assert response.status_code == 200
    body = response.json()
    assert body["contract_name"] == "lamesa_solar_west"
    assert body["settlement_point"] == "HB_WEST"
    assert 0 < body["capture_rate"] < 2
    assert body["counterparty"] == "buyer"
    assert len(body["monthly"]) >= 1
    assert body["monthly"][0]["month"].startswith("Jan")


def test_settlement_reports_escalated_strike(offline, contract):
    escalating = {**contract, "escalation_pct_yr": 2.5}

    body = client.post("/api/settlement", json=_request(escalating)).json()

    # term starts 2023, so 2025 is two years of compounding
    assert body["base_strike_usd_mwh"] == pytest.approx(32.0)
    assert body["strike_usd_mwh"] == pytest.approx(32.0 * 1.025**2)


def test_settlement_flags_an_out_of_term_year(offline, contract):
    body = client.post("/api/settlement", json=_request(contract, year=2019)).json()

    assert body["in_term"] is False


def test_seller_view_flips_the_reported_cash_sign(offline, contract):
    buyer = client.post("/api/settlement", json=_request(contract)).json()
    seller_contract = {**contract, "counterparty_view": "seller"}
    seller = client.post("/api/settlement", json=_request(seller_contract)).json()

    assert seller["counterparty"] == "seller"
    assert seller["cash_to_counterparty_usd"] == pytest.approx(
        -buyer["cash_to_counterparty_usd"]
    )


def test_basis_requires_node_settlement(offline, contract):
    response = client.post("/api/basis", json=_request(contract))

    assert response.status_code == 400
    assert "settle_at_node" in response.json()["detail"]


def test_basis_returns_generation_weighted_cost(offline, contract):
    body = client.post(
        "/api/basis", json=_request(contract, settle_at_node=True)
    ).json()

    # the fixture puts the node a flat $6 below the hub
    assert body["mean_basis_usd_mwh"] == pytest.approx(-6.0)
    assert body["cost_of_basis_usd_mwh"] == pytest.approx(-6.0)
    assert body["negative_basis_share"] == pytest.approx(1.0)


def test_scenarios_returns_the_designed_cases(offline, contract):
    body = client.post("/api/scenarios", json=_request(contract)).json()

    names = [row["scenario"] for row in body["scenarios"]]
    assert names == [
        "base",
        "p90_production",
        "price_collapse",
        "bad_basis_year",
        "combined_stress",
    ]
    assert body["scenarios"][0]["label"] == "Base case"


def test_storage_returns_uplift_and_average_day(offline, contract):
    body = client.post("/api/storage", json=_request(contract)).json()

    assert body["capture_rate_with_storage"] > body["capture_rate_base"]
    assert body["uplift_points"] > 0
    assert len(body["average_day"]) == 24


def test_storage_400s_when_the_contract_has_no_battery(offline, contract):
    no_storage = {k: v for k, v in contract.items() if k != "storage"}

    response = client.post("/api/storage", json=_request(no_storage))

    assert response.status_code == 400
    assert "no storage" in response.json()["detail"]


def test_invalid_contract_is_rejected_with_field_detail(contract):
    bad = {**contract, "project": {**contract["project"], "tilt_deg": 190}}

    response = client.post("/api/contracts/validate", json=bad)

    assert response.status_code == 422
    assert "tilt_deg" in str(response.json())


def test_missing_api_key_surfaces_as_a_400_not_a_500(monkeypatch, contract):
    def _no_key(*args, **kwargs):
        raise RuntimeError("NREL_API_KEY and NREL_API_EMAIL must be set")

    monkeypatch.setattr("vppa.api.main.fetch_pvwatts_generation", _no_key)

    response = client.post("/api/settlement", json=_request(contract))

    # missing configuration is a bad request, not a server fault
    assert response.status_code == 400
    assert "NREL_API_KEY" in response.json()["detail"]


def test_contract_picker_works_from_any_working_directory(tmp_path, monkeypatch):
    # CONTRACTS_DIR used to be a bare relative Path("contracts"), so serving
    # the API from anywhere but the repo root returned an empty picker
    monkeypatch.chdir(tmp_path)

    response = client.get("/api/contracts")

    assert response.status_code == 200
    assert {row["file"] for row in response.json()} >= {
        "lamesa_west.yaml",
        "noble_north.yaml",
        "sunvalley_central.yaml",
    }


def test_validate_accepts_a_mounting_choice_and_defaults_to_fixed(example_contract):
    payload = example_contract.model_dump(mode="json")
    assert client.post("/api/contracts/validate", json=payload).json()["project"][
        "tracking"
    ] == "fixed"

    payload["project"]["tracking"] = "single_axis_backtracked"
    assert client.post("/api/contracts/validate", json=payload).status_code == 200

    payload["project"]["tracking"] = "dual_axis"
    assert client.post("/api/contracts/validate", json=payload).status_code == 422


def test_contract_summaries_carry_what_the_picker_shows(offline):
    rows = client.get("/api/contracts").json()
    lamesa = next(r for r in rows if r["file"] == "lamesa_west.yaml")

    assert lamesa["label"] == "Lamesa Solar"
    assert lamesa["location"] == "Dawson County, TX"
    assert lamesa["contract_mw"] == 102
    assert lamesa["has_storage"] is True
    assert lamesa["settlement_point"] == "HB_WEST"
    assert lamesa["commercial_operation"] == "2017-04-01"


def test_a_contract_without_provenance_still_summarises(offline):
    rows = client.get("/api/contracts").json()
    demo = next(r for r in rows if r["file"] == "example_ercot_west.yaml")

    assert demo["location"] is None
    assert demo["label"] == "Example deal (schema demo)"


def test_availability_reports_a_runnable_default_year(example_contract):
    body = client.post(
        "/api/availability", json={"contract": example_contract.model_dump(mode="json")}
    ).json()

    assert body["default_year"] in {row["year"] for row in body["years"]}
    default = next(r for r in body["years"] if r["year"] == body["default_year"])
    assert default["analysis"]["available"]


def test_availability_marks_a_contract_without_a_battery(example_contract):
    body = client.post(
        "/api/availability", json={"contract": example_contract.model_dump(mode="json")}
    ).json()

    assert body["storage"]["available"] is False
    assert "no paired battery" in body["storage"]["reason"]

    with_battery = example_contract.model_dump(mode="json")
    with_battery["storage"] = {
        "power_mw": 50, "duration_hours": 4, "round_trip_efficiency": 0.85
    }
    body = client.post("/api/availability", json={"contract": with_battery}).json()
    assert body["storage"]["available"] is True


def test_geocode_endpoint_shapes_places_for_the_editor(monkeypatch):
    from vppa.ingest.geocode import Place

    monkeypatch.setattr(
        "vppa.api.main.geocode_search",
        lambda q, limit: [
            Place("Pecos County, Texas", 30.88, -102.72, county="Pecos", state="Texas")
        ],
    )

    body = client.get("/api/geocode", params={"q": "Pecos County"}).json()

    assert body["places"][0]["county"] == "Pecos"
    assert body["places"][0]["lat"] == 30.88


def test_geocode_reports_a_donated_service_being_down_as_503(monkeypatch):
    def boom(q, limit):
        raise OSError("connection refused")

    monkeypatch.setattr("vppa.api.main.geocode_search", boom)

    response = client.get("/api/geocode", params={"q": "anywhere"})

    # not a 500: the request was fine, the upstream was not
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]


def test_geocode_limit_is_clamped(monkeypatch):
    seen = []

    def capture(q, limit):
        seen.append(limit)
        return []

    monkeypatch.setattr("vppa.api.main.geocode_search", capture)

    client.get("/api/geocode", params={"q": "x", "limit": 500})
    client.get("/api/geocode", params={"q": "x", "limit": 0})

    assert seen == [10, 1]
