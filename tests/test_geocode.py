import pytest

from vppa.ingest import geocode

SEARCH_HIT = [
    {
        "display_name": "Dawson County, Texas, United States",
        "lat": "32.7410762",
        "lon": "-101.9576048",
        "address": {"county": "Dawson County", "state": "Texas"},
    }
]


@pytest.fixture(autouse=True)
def clear_caches(monkeypatch):
    """Each test starts cold, and no test ever waits on the real throttle."""
    geocode._forward_cache.clear()
    geocode._reverse_cache.clear()
    monkeypatch.setattr(geocode, "_MIN_INTERVAL_SECONDS", 0.0)


def stub(monkeypatch, payload, calls=None):
    def fake(path, params):
        if calls is not None:
            calls.append((path, params))
        return payload

    monkeypatch.setattr(geocode, "_get", fake)


def test_search_returns_places_with_the_county_suffix_stripped(monkeypatch):
    # Nominatim says "Dawson County"; contracts store "Dawson", and a mismatch
    # here would show up as a changed field the moment a place is applied
    stub(monkeypatch, SEARCH_HIT)

    place = geocode.search("Dawson County Texas")[0]

    assert place.county == "Dawson"
    assert place.state == "Texas"
    assert place.lat == pytest.approx(32.7410762)


def test_an_empty_query_never_reaches_the_service(monkeypatch):
    calls = []
    stub(monkeypatch, SEARCH_HIT, calls)

    assert geocode.search("   ") == []
    assert calls == []


def test_repeat_searches_are_served_from_cache(monkeypatch):
    calls = []
    stub(monkeypatch, SEARCH_HIT, calls)

    geocode.search("Dawson County Texas")
    geocode.search("dawson county texas")  # same query, different case

    assert len(calls) == 1


def test_reverse_buckets_coordinates_to_about_100_m(monkeypatch):
    calls = []
    stub(
        monkeypatch,
        {
            "display_name": "Dawson County, Texas",
            "lat": "32.741",
            "lon": "-101.958",
            "address": {"county": "Dawson County", "state": "Texas"},
        },
        calls,
    )

    # Rounding puts nearby coordinates in a shared bucket; it does not promise
    # that every neighbour shares one, since a pair can straddle a boundary.
    # What it does promise is that precision finer than EIA-860 reports never
    # generates a request of its own.
    geocode.reverse(32.71561, -101.92652)
    geocode.reverse(32.71592, -101.92671)

    assert len(calls) == 1
    assert calls[0][1]["lat"] == 32.716
    assert calls[0][1]["lon"] == -101.927


def test_reverse_returns_none_when_nominatim_reports_no_match(monkeypatch):
    stub(monkeypatch, {"error": "Unable to geocode"})

    assert geocode.reverse(0.0, 0.0) is None


def test_the_throttle_spaces_requests_out(monkeypatch):
    """Nominatim's policy is one request per second; that has to be enforced
    here, because the browser calls this through the API on every search."""
    monkeypatch.setattr(geocode, "_MIN_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(geocode, "_last_request", 0.0)

    slept = []
    monkeypatch.setattr(geocode.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(geocode.requests, "get", lambda *a, **k: _Response())

    geocode._get("/search", {"q": "a"})
    geocode._get("/search", {"q": "b"})

    assert slept, "second back-to-back request was not throttled"


class _Response:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return []
