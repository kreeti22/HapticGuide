"""
test_navigation_routing.py
--------------------------
Phase 4: OSRM route calculation tests.

Tests URL construction with longitude,latitude ordering, JSON response parsing,
step and maneuver extraction, distance/duration calculations, error handling
(NoRoute, NoSegment, network failure, timeouts, malformed JSON), and NavigationState integration.

No live network calls — HTTP responses are mocked.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest

import globals
from navigation import session
from navigation.interfaces import RoutingService
from navigation.routing import (
    DEFAULT_OSRM_URL,
    OsrmRoutingService,
    RouteCalculationError,
    build_osrm_url,
    calculate_route_and_update_state,
    format_step_instruction,
    map_maneuver_code,
    parse_osrm_response,
)
from navigation.state import (
    GeoPoint,
    GpsFix,
    NavigationState,
    NavigationStatus,
    PlaceCandidate,
    RouteSnapshot,
    RouteStatus,
)


@pytest.fixture
def origin_cp():
    """Connaught Place, New Delhi (28.6139 N, 77.2090 E)."""
    return GeoPoint(latitude=28.6139, longitude=77.2090)


@pytest.fixture
def destination_barakhamba():
    """Barakhamba Road, New Delhi (28.6280 N, 77.2280 E)."""
    return GeoPoint(latitude=28.6280, longitude=77.2280)


@pytest.fixture
def sample_osrm_payload():
    """Standard multi-step OSRM JSON response payload."""
    return {
        "code": "Ok",
        "routes": [
            {
                "geometry": {
                    "coordinates": [
                        [77.209000, 28.613900],
                        [77.215000, 28.620000],
                        [77.228000, 28.628000],
                    ],
                    "type": "LineString",
                },
                "legs": [
                    {
                        "summary": "Barakhamba Road",
                        "weight": 340.5,
                        "duration": 340.5,
                        "distance": 2150.8,
                        "steps": [
                            {
                                "distance": 450.2,
                                "duration": 65.0,
                                "name": "Connaught Circus",
                                "mode": "driving",
                                "maneuver": {
                                    "bearing_after": 45,
                                    "bearing_before": 0,
                                    "location": [77.209000, 28.613900],
                                    "type": "depart",
                                    "modifier": "straight",
                                },
                            },
                            {
                                "distance": 1200.6,
                                "duration": 195.5,
                                "name": "Barakhamba Road",
                                "mode": "driving",
                                "maneuver": {
                                    "bearing_after": 90,
                                    "bearing_before": 45,
                                    "location": [77.215000, 28.620000],
                                    "type": "turn",
                                    "modifier": "right",
                                },
                            },
                            {
                                "distance": 500.0,
                                "duration": 80.0,
                                "name": "Barakhamba Road",
                                "mode": "driving",
                                "maneuver": {
                                    "bearing_after": 0,
                                    "bearing_before": 90,
                                    "location": [77.225000, 28.626000],
                                    "type": "turn",
                                    "modifier": "slight left",
                                },
                            },
                            {
                                "distance": 0.0,
                                "duration": 0.0,
                                "name": "Barakhamba Road",
                                "mode": "driving",
                                "maneuver": {
                                    "bearing_after": 0,
                                    "bearing_before": 0,
                                    "location": [77.228000, 28.628000],
                                    "type": "arrive",
                                },
                            },
                        ],
                    }
                ],
                "weight_name": "routability",
                "weight": 340.5,
                "duration": 340.5,
                "distance": 2150.8,
            }
        ],
        "waypoints": [
            {
                "hint": "hint_origin",
                "distance": 2.1,
                "name": "Connaught Circus",
                "location": [77.209000, 28.613900],
            },
            {
                "hint": "hint_dest",
                "distance": 3.4,
                "name": "Barakhamba Road",
                "location": [77.228000, 28.628000],
            },
        ],
    }


# ---------------------------------------------------------------------------
# URL Construction & Coordinate Ordering Tests
# ---------------------------------------------------------------------------

def test_build_osrm_url_coordinate_ordering(origin_cp, destination_barakhamba):
    """
    CRITICAL: Verify longitude precedes latitude for both origin and destination.
    """
    url = build_osrm_url(origin_cp, destination_barakhamba)

    # Origin: lon=77.209000, lat=28.613900
    # Destination: lon=77.228000, lat=28.628000
    expected_coord_segment = "77.209000,28.613900;77.228000,28.628000"

    assert expected_coord_segment in url
    assert url.startswith("https://router.project-osrm.org/route/v1/driving/")
    assert "steps=true" in url
    assert "overview=full" in url
    assert "geometries=geojson" in url


def test_build_osrm_url_custom_base_and_profile(origin_cp, destination_barakhamba):
    url = build_osrm_url(
        origin_cp,
        destination_barakhamba,
        base_url="http://localhost:5000",
        profile="walking",
    )
    assert url.startswith("http://localhost:5000/route/v1/walking/77.209000,28.613900;77.228000,28.628000")


# ---------------------------------------------------------------------------
# Maneuver Formatting & Mapping Tests
# ---------------------------------------------------------------------------

def test_map_maneuver_code():
    assert map_maneuver_code("turn", "left") == "LEFT"
    assert map_maneuver_code("turn", "slight left") == "LEFT"
    assert map_maneuver_code("turn", "sharp left") == "LEFT"
    assert map_maneuver_code("turn", "right") == "RIGHT"
    assert map_maneuver_code("turn", "slight right") == "RIGHT"
    assert map_maneuver_code("depart", "straight") == "STRAIGHT"
    assert map_maneuver_code("arrive") == "ARRIVAL"


def test_format_step_instruction():
    assert "Head straight on Main St" in format_step_instruction("depart", "straight", "Main St")
    assert "Turn right onto 1st Ave" in format_step_instruction("turn", "right", "1st Ave")
    assert "Turn left onto 2nd Ave" in format_step_instruction("turn", "left", "2nd Ave")
    assert "Take a slight right onto Hwy 1" or "Turn slight right onto Hwy 1" in format_step_instruction("turn", "slight right", "Hwy 1")
    assert "arrived" in format_step_instruction("arrive", None, "Main St").lower()


# ---------------------------------------------------------------------------
# Response Parsing Tests
# ---------------------------------------------------------------------------

def test_parse_osrm_response_success(sample_osrm_payload, origin_cp, destination_barakhamba):
    route = parse_osrm_response(sample_osrm_payload, origin_cp, destination_barakhamba)

    assert isinstance(route, RouteSnapshot)
    assert route.total_distance_m == 2150.8
    assert route.total_duration_s == 340.5
    assert route.remaining_distance_m == 2150.8
    assert route.distance_to_next_m == 450.2

    # Instructions
    assert route.current is not None
    assert "Head straight on Connaught Circus" in route.current.text
    assert route.current.distance_m == 450.2

    assert route.next is not None
    assert "Turn right onto Barakhamba Road" in route.next.text
    assert route.next.distance_m == 1200.6

    # Steps
    assert len(route.steps) == 4
    step0 = route.steps[0]
    assert step0.road_name == "Connaught Circus"
    assert step0.distance_m == 450.2
    assert step0.location is not None
    assert step0.location.latitude == 28.6139
    assert step0.location.longitude == 77.2090

    step1 = route.steps[1]
    assert step1.road_name == "Barakhamba Road"
    assert step1.maneuver_type == "turn"
    assert step1.maneuver_modifier == "right"
    assert step1.location.latitude == 28.6200
    assert step1.location.longitude == 77.2150

    # Geometry
    assert route.geometry is not None
    assert route.geometry["type"] == "LineString"
    assert len(route.geometry["coordinates"]) == 3


def test_parse_osrm_response_no_routes(origin_cp, destination_barakhamba):
    payload = {"code": "Ok", "routes": []}
    with pytest.raises(RouteCalculationError) as exc_info:
        parse_osrm_response(payload, origin_cp, destination_barakhamba)
    assert "no routes" in str(exc_info.value).lower()


def test_parse_osrm_response_error_code(origin_cp, destination_barakhamba):
    payload = {"code": "NoRoute", "message": "Impossible route between points"}
    with pytest.raises(RouteCalculationError) as exc_info:
        parse_osrm_response(payload, origin_cp, destination_barakhamba)
    assert "NoRoute" in str(exc_info.value) or "Impossible" in str(exc_info.value)


def test_parse_osrm_response_malformed(origin_cp, destination_barakhamba):
    with pytest.raises(RouteCalculationError):
        parse_osrm_response({"code": "Ok", "routes": "invalid"}, origin_cp, destination_barakhamba)


# ---------------------------------------------------------------------------
# OsrmRoutingService Unit Tests
# ---------------------------------------------------------------------------

def test_osrm_service_implements_protocol():
    service = OsrmRoutingService()
    assert isinstance(service, RoutingService)


def test_service_valid_origin_and_destination(sample_osrm_payload, origin_cp, destination_barakhamba):
    mock_requester = MagicMock(return_value=json.dumps(sample_osrm_payload))
    service = OsrmRoutingService(http_requester=mock_requester)

    route = service.calculate_route(origin_cp, destination_barakhamba)
    assert route is not None
    assert route.total_distance_m == 2150.8

    mock_requester.assert_called_once()
    called_url = mock_requester.call_args[0][0]
    assert "77.209000,28.613900;77.228000,28.628000" in called_url


def test_service_osrm_no_route_error(origin_cp, destination_barakhamba):
    no_route_payload = json.dumps({"code": "NoRoute", "message": "No route found"})
    mock_requester = MagicMock(return_value=no_route_payload)
    service = OsrmRoutingService(http_requester=mock_requester)

    with pytest.raises(RouteCalculationError) as exc_info:
        service.calculate_route(origin_cp, destination_barakhamba)
    assert "NoRoute" in str(exc_info.value) or "No route found" in str(exc_info.value)


def test_service_osrm_no_segment_error(origin_cp, destination_barakhamba):
    no_seg_payload = json.dumps({"code": "NoSegment", "message": "Could not find a matching segment for coordinate"})
    mock_requester = MagicMock(return_value=no_seg_payload)
    service = OsrmRoutingService(http_requester=mock_requester)

    with pytest.raises(RouteCalculationError) as exc_info:
        service.calculate_route(origin_cp, destination_barakhamba)
    assert "NoSegment" in str(exc_info.value)


def test_service_network_failure(origin_cp, destination_barakhamba):
    def failing_requester(url, timeout):
        raise OSError("Connection refused by OSRM")

    service = OsrmRoutingService(http_requester=failing_requester)
    with pytest.raises(RouteCalculationError) as exc_info:
        service.calculate_route(origin_cp, destination_barakhamba)
    assert "network failure" in str(exc_info.value).lower()


def test_service_timeout(origin_cp, destination_barakhamba):
    def timeout_requester(url, timeout):
        raise TimeoutError("OSRM query timed out")

    service = OsrmRoutingService(http_requester=timeout_requester)
    with pytest.raises(RouteCalculationError) as exc_info:
        service.calculate_route(origin_cp, destination_barakhamba)
    assert "network failure" in str(exc_info.value).lower() or "timeout" in str(exc_info.value).lower()


def test_service_malformed_html_response(origin_cp, destination_barakhamba):
    mock_requester = MagicMock(return_value="<html>502 Bad Gateway</html>")
    service = OsrmRoutingService(http_requester=mock_requester)

    with pytest.raises(RouteCalculationError) as exc_info:
        service.calculate_route(origin_cp, destination_barakhamba)
    assert "malformed" in str(exc_info.value).lower()


def test_service_invalid_coordinates(origin_cp, destination_barakhamba):
    service = OsrmRoutingService()
    with pytest.raises(ValueError):
        service.calculate_route(GeoPoint(latitude=95.0, longitude=77.0), destination_barakhamba)
    with pytest.raises(ValueError):
        service.calculate_route(origin_cp, GeoPoint(latitude=28.0, longitude=190.0))


# ---------------------------------------------------------------------------
# NavigationState Integration Tests
# ---------------------------------------------------------------------------

def test_calculate_route_and_update_state_success(sample_osrm_payload, origin_cp, destination_barakhamba):
    state = NavigationState()
    state.set_current_location(GpsFix(latitude=28.6139, longitude=77.2090, accuracy_m=4.0))
    state.begin_search()
    state.set_destination(PlaceCandidate(name="Barakhamba Place", location=destination_barakhamba, distance_m=2150.0))
    assert state.status is NavigationStatus.DESTINATION_FOUND

    service = OsrmRoutingService(http_requester=MagicMock(return_value=json.dumps(sample_osrm_payload)))
    route = calculate_route_and_update_state(state, service=service)

    assert route is not None
    assert state.status is NavigationStatus.ROUTE_READY
    assert state.route_status is RouteStatus.READY
    assert state.total_route_distance_m == 2150.8
    assert state.total_route_duration_s == 340.5
    assert state.distance_to_next_m == 450.2
    assert state.remaining_distance_m == 2150.8
    assert state.current_instruction is not None
    assert state.next_instruction is not None
    assert state.active_route is route
    assert state.error_message is None

    snap = state.snapshot()
    assert snap["status"] == "ROUTE_READY"
    assert snap["route_status"] == "READY"
    assert snap["total_route_distance_m"] == 2150.8
    assert snap["total_route_duration_s"] == 340.5
    assert snap["route_steps_count"] == 4
    assert snap["distance_to_next_m"] == 450.2


def test_calculate_route_fails_when_no_gps():
    state = NavigationState()
    state.destination = GeoPoint(latitude=28.6280, longitude=77.2280)
    route = calculate_route_and_update_state(state)
    assert route is None
    assert state.status is NavigationStatus.ERROR
    assert "GPS location unavailable" in (state.error_message or "")


def test_calculate_route_fails_when_no_destination():
    state = NavigationState()
    state.set_current_location(GpsFix(latitude=28.6139, longitude=77.2090))
    route = calculate_route_and_update_state(state)
    assert route is None
    assert state.status is NavigationStatus.ERROR
    assert "Destination" in (state.error_message or "")


def test_calculate_route_fails_on_osrm_error(origin_cp, destination_barakhamba):
    state = NavigationState()
    state.set_current_location(GpsFix(latitude=28.6139, longitude=77.2090))
    state.destination = destination_barakhamba
    state.status = NavigationStatus.DESTINATION_FOUND

    def failing_requester(url, timeout):
        raise RouteCalculationError("OSRM NoRoute")

    service = OsrmRoutingService(http_requester=failing_requester)
    route = calculate_route_and_update_state(state, service=service)

    assert route is None
    assert state.status is NavigationStatus.ERROR
    assert state.route_status is RouteStatus.FAILED
    assert "Route calculation failed" in (state.error_message or "")


def test_routing_does_not_modify_obstacle_state(sample_osrm_payload, origin_cp, destination_barakhamba):
    state = NavigationState()
    state.set_current_location(GpsFix(latitude=28.6139, longitude=77.2090))
    state.destination = destination_barakhamba
    state.status = NavigationStatus.DESTINATION_FOUND

    with globals.command_lock:
        orig = dict(globals.latest_command)
        globals.latest_command.update({"left": 150, "front": 0, "right": 0, "back": 200})
        before = dict(globals.latest_command)

    try:
        service = OsrmRoutingService(http_requester=MagicMock(return_value=json.dumps(sample_osrm_payload)))
        calculate_route_and_update_state(state, service=service)

        with globals.command_lock:
            after = dict(globals.latest_command)
    finally:
        with globals.command_lock:
            globals.latest_command.update(orig)

    assert after == before
    assert after["left"] == 150
    assert after["back"] == 200


# ---------------------------------------------------------------------------
# FastAPI HTTP Endpoint Tests (/nav/route)
# ---------------------------------------------------------------------------

def test_fastapi_nav_route_endpoint(sample_osrm_payload):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from navigation.routes import router

    session.reset_session()
    state = session.get_state()
    state.set_current_location(GpsFix(latitude=28.6139, longitude=77.2090, accuracy_m=3.0))
    state.destination = GeoPoint(latitude=28.6280, longitude=77.2280)
    state.destination_name = "Barakhamba Road"
    state.status = NavigationStatus.DESTINATION_FOUND

    app = fastapi.FastAPI()
    app.include_router(router)
    client = TestClient(app)

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
        return MockResponse(json.dumps(sample_osrm_payload))

    urllib.request.urlopen = mock_urlopen

    try:
        resp = client.post("/nav/route", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["status"] == "ROUTE_READY"
        assert body["route"]["total_distance_m"] == 2150.8
        assert body["route"]["steps_count"] == 4

        # Alias /nav/calculate-route
        resp_alias = client.post("/nav/calculate-route", json={})
        assert resp_alias.status_code == 200
        assert resp_alias.json()["ok"] is True
    finally:
        urllib.request.urlopen = orig_urlopen
        session.reset_session()
