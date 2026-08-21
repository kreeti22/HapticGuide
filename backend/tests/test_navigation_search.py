"""
test_navigation_search.py
-------------------------
Phase 3: OpenStreetMap / Overpass destination search tests.

Tests query cleaning, Overpass QL construction, Haversine distance calculation,
Overpass response parsing (nodes, ways with center, tags), nearest selection,
error handling (network failure, timeouts, malformed JSON, no results),
and NavigationState integration.

No live network calls — HTTP responses are mocked.
"""

import json
import math
import sys
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest

import globals
from navigation import session
from navigation.interfaces import DestinationSearchService
from navigation.search import (
    DEFAULT_OVERPASS_URL,
    DestinationSearchError,
    OverpassSearchService,
    build_overpass_query,
    clean_destination_query,
    haversine_distance_m,
    parse_overpass_response,
    search_destination_and_update_state,
)
from navigation.state import (
    GeoPoint,
    GpsFix,
    GpsHealth,
    NavigationState,
    NavigationStatus,
    PlaceCandidate,
    RouteStatus,
)


@pytest.fixture
def nav_state():
    state = NavigationState()
    # Provide a valid GPS location
    state.set_current_location(
        GpsFix(latitude=28.6139, longitude=77.2090, accuracy_m=5.0, received_at_monotonic=100.0)
    )
    return state


@pytest.fixture
def origin_cp():
    """Connaught Place, New Delhi coordinates."""
    return GeoPoint(latitude=28.6139, longitude=77.2090)


# ---------------------------------------------------------------------------
# Query Cleaning Tests
# ---------------------------------------------------------------------------

def test_clean_destination_query_variants():
    assert clean_destination_query("nearest KFC") == "KFC"
    assert clean_destination_query("KFC") == "KFC"
    assert clean_destination_query("the nearest KFC") == "KFC"
    assert clean_destination_query("find nearest KFC") == "KFC"
    assert clean_destination_query("take me to nearest KFC") == "KFC"
    assert clean_destination_query("take me to the nearest hospital") == "hospital"
    assert clean_destination_query("navigate to nearest McDonald's") == "McDonald's"
    assert clean_destination_query("go to nearest coffee shop") == "coffee shop"
    assert clean_destination_query("coffee shop near me") == "coffee shop"
    assert clean_destination_query("closest pharmacy") == "pharmacy"
    assert clean_destination_query("pharmacy nearby") == "pharmacy"
    assert clean_destination_query("search for nearest gas station") == "gas station"
    assert clean_destination_query("") == ""
    assert clean_destination_query("   ") == ""


# ---------------------------------------------------------------------------
# Haversine Distance Tests
# ---------------------------------------------------------------------------

def test_haversine_distance_identical_points():
    assert haversine_distance_m(28.6139, 77.2090, 28.6139, 77.2090) == 0.0


def test_haversine_distance_known_distance():
    # 1 degree latitude difference is roughly 111.19 km
    dist = haversine_distance_m(0.0, 0.0, 1.0, 0.0)
    assert 110_000 < dist < 112_000

    # Short distance in city (~111 meters)
    dist_short = haversine_distance_m(28.6139, 77.2090, 28.6149, 77.2090)
    assert 100 < dist_short < 120


# ---------------------------------------------------------------------------
# Overpass QL Query Builder Tests
# ---------------------------------------------------------------------------

def test_build_overpass_query_format(origin_cp):
    ql = build_overpass_query("KFC", origin_cp, radius_m=3000)
    assert "[out:json]" in ql
    assert "around:3000,28.613900,77.209000" in ql
    assert 'node["name"~"KFC",i]' in ql
    assert 'way["name"~"KFC",i]' in ql
    assert 'node["brand"~"KFC",i]' in ql
    assert 'way["brand"~"KFC",i]' in ql
    assert "out center tags;" in ql


def test_build_overpass_query_category_amenity(origin_cp):
    ql = build_overpass_query("coffee shop", origin_cp, radius_m=5000)
    assert 'node["amenity"="cafe"]' in ql
    assert 'way["amenity"="cafe"]' in ql
    assert 'node["shop"="coffee"]' in ql


def test_build_overpass_query_escapes_special_chars(origin_cp):
    ql = build_overpass_query('Joe\'s "Special" (Bar & Grill)', origin_cp, radius_m=2000)
    assert r'\"Special\"' in ql
    assert r"\(" in ql
    assert r"\)" in ql


# ---------------------------------------------------------------------------
# Response Parsing Tests
# ---------------------------------------------------------------------------

def test_parse_overpass_response_nodes_and_ways(origin_cp):
    mock_data = {
        "elements": [
            {
                "type": "node",
                "id": 101,
                "lat": 28.6149,
                "lon": 77.2090,
                "tags": {
                    "name": "KFC Connaught",
                    "amenity": "fast_food",
                    "brand": "KFC",
                },
            },
            {
                "type": "way",
                "id": 202,
                "center": {
                    "lat": 28.6200,
                    "lon": 77.2150,
                },
                "tags": {
                    "name": "KFC Barakhamba",
                    "brand": "KFC",
                },
            },
        ]
    }

    candidates = parse_overpass_response(mock_data, origin_cp, fallback_name="KFC")
    assert len(candidates) == 2

    # Nearest first
    first = candidates[0]
    assert first.name == "KFC Connaught"
    assert first.location.latitude == 28.6149
    assert first.location.longitude == 77.2090
    assert first.osm_id == 101
    assert first.osm_type == "node"
    assert first.distance_m is not None and first.distance_m < 200

    second = candidates[1]
    assert second.name == "KFC Barakhamba"
    assert second.location.latitude == 28.6200
    assert second.location.longitude == 77.2150
    assert second.osm_id == 202
    assert second.osm_type == "way"
    assert second.distance_m is not None and second.distance_m > first.distance_m


def test_parse_overpass_response_multiple_candidates_sorted_by_nearest(origin_cp):
    mock_data = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 28.6300,  # ~1.8 km away
                "lon": 77.2090,
                "tags": {"name": "KFC Far"},
            },
            {
                "type": "node",
                "id": 2,
                "lat": 28.6145,  # ~66 meters away (NEAREST)
                "lon": 77.2090,
                "tags": {"name": "KFC Nearest"},
            },
            {
                "type": "node",
                "id": 3,
                "lat": 28.6180,  # ~450 meters away
                "lon": 77.2090,
                "tags": {"name": "KFC Medium"},
            },
        ]
    }

    candidates = parse_overpass_response(mock_data, origin_cp)
    assert len(candidates) == 3
    assert candidates[0].name == "KFC Nearest"
    assert candidates[1].name == "KFC Medium"
    assert candidates[2].name == "KFC Far"
    assert candidates[0].distance_m < candidates[1].distance_m < candidates[2].distance_m


def test_parse_overpass_response_empty_elements(origin_cp):
    candidates = parse_overpass_response({"elements": []}, origin_cp)
    assert candidates == []


def test_parse_overpass_response_invalid_structure(origin_cp):
    assert parse_overpass_response({}, origin_cp) == []
    assert parse_overpass_response({"elements": "invalid"}, origin_cp) == []
    assert parse_overpass_response({"elements": [{"invalid": True}]}, origin_cp) == []


# ---------------------------------------------------------------------------
# OverpassSearchService Unit Tests
# ---------------------------------------------------------------------------

def test_overpass_search_service_implements_protocol():
    service = OverpassSearchService()
    assert isinstance(service, DestinationSearchService)


def test_valid_gps_and_nearest_kfc_search_success(origin_cp):
    mock_json = json.dumps({
        "elements": [
            {
                "type": "node",
                "id": 555,
                "lat": 28.6142,
                "lon": 77.2091,
                "tags": {"name": "KFC Regal Building", "brand": "KFC"},
            }
        ]
    })

    mock_requester = MagicMock(return_value=mock_json)
    service = OverpassSearchService(http_requester=mock_requester)

    candidate = service.search_nearby("nearest KFC", origin_cp)
    assert candidate is not None
    assert candidate.name == "KFC Regal Building"
    assert candidate.location.latitude == 28.6142
    assert candidate.location.longitude == 77.2091
    assert candidate.osm_id == 555
    assert candidate.distance_m is not None
    assert candidate.distance_m > 0

    mock_requester.assert_called_once()
    args = mock_requester.call_args[0]
    assert args[0] == DEFAULT_OVERPASS_URL
    assert "KFC" in args[1]


def test_search_no_matching_destination(origin_cp):
    mock_requester = MagicMock(return_value=json.dumps({"elements": []}))
    service = OverpassSearchService(http_requester=mock_requester)

    candidate = service.search_nearby("nearest NonExistentStoreXYZ", origin_cp)
    assert candidate is None


def test_search_overpass_network_failure(origin_cp):
    def failing_requester(url, ql, timeout):
        raise OSError("Connection refused")

    service = OverpassSearchService(http_requester=failing_requester)

    with pytest.raises(DestinationSearchError) as exc_info:
        service.search_nearby("nearest KFC", origin_cp)
    assert "network failure" in str(exc_info.value).lower()


def test_search_overpass_malformed_response(origin_cp):
    mock_requester = MagicMock(return_value="<html>504 Gateway Timeout</html>")
    service = OverpassSearchService(http_requester=mock_requester)

    with pytest.raises(DestinationSearchError) as exc_info:
        service.search_nearby("nearest KFC", origin_cp)
    assert "malformed" in str(exc_info.value).lower()


def test_search_invalid_origin_coordinates():
    service = OverpassSearchService()
    with pytest.raises(ValueError):
        service.search_nearby("KFC", GeoPoint(latitude=120.0, longitude=77.0))
    with pytest.raises(ValueError):
        service.search_nearby("KFC", GeoPoint(latitude=28.0, longitude=-200.0))
    with pytest.raises(ValueError):
        service.search_nearby("   ", GeoPoint(latitude=28.0, longitude=77.0))


# ---------------------------------------------------------------------------
# Navigation State Integration Tests
# ---------------------------------------------------------------------------

def test_search_destination_and_update_state_success(nav_state):
    mock_json = json.dumps({
        "elements": [
            {
                "type": "node",
                "id": 999,
                "lat": 28.6145,
                "lon": 77.2095,
                "tags": {"name": "KFC Plaza", "brand": "KFC"},
            }
        ]
    })
    service = OverpassSearchService(http_requester=MagicMock(return_value=mock_json))

    candidate = search_destination_and_update_state(
        state=nav_state,
        query="nearest KFC",
        service=service,
    )

    assert candidate is not None
    assert nav_state.status is NavigationStatus.DESTINATION_FOUND
    assert nav_state.destination_name == "KFC Plaza"
    assert nav_state.destination is not None
    assert nav_state.destination.latitude == 28.6145
    assert nav_state.destination.longitude == 77.2095
    assert nav_state.destination_distance_m is not None
    assert nav_state.destination_candidate is candidate
    assert nav_state.error_message is None

    snap = nav_state.snapshot()
    assert snap["status"] == "DESTINATION_FOUND"
    assert snap["destination_query"] == "nearest KFC"
    assert snap["destination_name"] == "KFC Plaza"
    assert snap["destination_latitude"] == 28.6145
    assert snap["destination_longitude"] == 77.2095
    assert snap["destination_distance_m"] == nav_state.destination_distance_m


def test_search_destination_fails_when_no_gps_location():
    state = NavigationState()  # No GPS fix set
    candidate = search_destination_and_update_state(state, "nearest KFC")
    assert candidate is None
    assert state.status is NavigationStatus.ERROR
    assert "GPS location unavailable" in (state.error_message or "")


def test_search_destination_fails_when_no_result_found(nav_state):
    service = OverpassSearchService(http_requester=MagicMock(return_value=json.dumps({"elements": []})))
    candidate = search_destination_and_update_state(nav_state, "nearest UnknownPlace", service=service)
    assert candidate is None
    assert nav_state.status is NavigationStatus.ERROR
    assert "No matching destination found" in (nav_state.error_message or "")


def test_search_destination_fails_when_service_errors(nav_state):
    def failing_requester(url, ql, timeout):
        raise DestinationSearchError("Simulated Overpass 503")

    service = OverpassSearchService(http_requester=failing_requester)
    candidate = search_destination_and_update_state(nav_state, "nearest KFC", service=service)
    assert candidate is None
    assert nav_state.status is NavigationStatus.ERROR
    assert "Destination search failed" in (nav_state.error_message or "")


def test_destination_search_does_not_modify_obstacle_state(nav_state):
    with globals.command_lock:
        original = dict(globals.latest_command)
        globals.latest_command.update({"left": 0, "front": 190, "right": 0, "back": 0})
        before = dict(globals.latest_command)

    try:
        mock_json = json.dumps({
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 28.6140,
                    "lon": 77.2090,
                    "tags": {"name": "KFC"},
                }
            ]
        })
        service = OverpassSearchService(http_requester=MagicMock(return_value=mock_json))
        search_destination_and_update_state(nav_state, "nearest KFC", service=service)

        with globals.command_lock:
            after = dict(globals.latest_command)
    finally:
        with globals.command_lock:
            globals.latest_command.update(original)

    assert after == before
    assert after["front"] == 190


# ---------------------------------------------------------------------------
# FastAPI HTTP Endpoint Tests (/nav/search & /nav/destination)
# ---------------------------------------------------------------------------

def test_fastapi_nav_search_endpoint():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from navigation.routes import router

    session.reset_session()
    state = session.get_state()
    # Set GPS fix on session
    state.set_current_location(GpsFix(latitude=28.6139, longitude=77.2090, accuracy_m=3.0))

    app = fastapi.FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Empty query rejected with 422
    empty_resp = client.post("/nav/search", json={"query": ""})
    assert empty_resp.status_code == 422

    # Mock Overpass response by monkeypatching urllib in routes or test
    mock_payload = {
        "elements": [
            {
                "type": "node",
                "id": 123,
                "lat": 28.6145,
                "lon": 77.2092,
                "tags": {"name": "KFC Connaught Place", "brand": "KFC"},
            }
        ]
    }

    import urllib.request
    orig_urlopen = urllib.request.urlopen

    class MockResponse:
        def __init__(self, data):
            self._data = data.encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=None):
        return MockResponse(json.dumps(mock_payload))

    urllib.request.urlopen = mock_urlopen

    try:
        resp = client.post("/nav/search", json={"query": "nearest KFC"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["status"] == "DESTINATION_FOUND"
        assert body["destination"]["name"] == "KFC Connaught Place"
        assert body["destination"]["latitude"] == 28.6145
        assert body["destination"]["longitude"] == 77.2092
        assert body["destination"]["distance_m"] is not None

        # Alias /nav/destination behaves identically
        resp_alias = client.post("/nav/destination", json={"query": "nearest KFC"})
        assert resp_alias.status_code == 200
        assert resp_alias.json()["ok"] is True
    finally:
        urllib.request.urlopen = orig_urlopen
        session.reset_session()
