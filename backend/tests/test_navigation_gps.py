"""
test_navigation_gps.py
----------------------
Phase 2: GPS ingest into navigation state.

No OSM, OSRM, Groq, or haptic playback.
HTTP tests skip if FastAPI is not installed.
"""

import math
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest

import globals
from navigation import session
from navigation.gps import (
    GpsIngestError,
    SessionLocationSource,
    STALE_AFTER_S,
    apply_gps_fault,
    apply_gps_fix,
    gps_status_payload,
    health_from_name,
    validate_coordinates,
)
from navigation.interfaces import LocationSource
from navigation.state import GpsHealth, NavigationState, NavigationStatus


@pytest.fixture
def nav_state():
    return NavigationState()


def test_valid_fix_updates_navigation_state(nav_state):
    payload = apply_gps_fix(nav_state, 28.6139, 77.2090, accuracy_m=4.5)
    assert nav_state.current_location is not None
    assert nav_state.current_location.latitude == 28.6139
    assert nav_state.current_location.longitude == 77.2090
    assert payload["gps_health"] == GpsHealth.ACTIVE.value
    assert payload["current_latitude"] == 28.6139
    assert payload["current_longitude"] == 77.2090
    assert payload["gps_stale"] is False
    assert nav_state.status is NavigationStatus.IDLE


def test_invalid_coordinates_rejected(nav_state):
    try:
        apply_gps_fix(nav_state, 120.0, 77.0)
    except GpsIngestError as exc:
        assert exc.health is GpsHealth.LOCATION_UNAVAILABLE
    else:
        raise AssertionError("Expected invalid latitude to fail.")
    assert nav_state.current_location is None


def test_missing_coordinates_are_unavailable(nav_state):
    try:
        apply_gps_fix(nav_state, None, 77.0)
    except GpsIngestError as exc:
        assert exc.health is GpsHealth.LOCATION_UNAVAILABLE
    else:
        raise AssertionError("Expected missing latitude to fail.")


def test_boolean_coordinates_rejected(nav_state):
    with pytest.raises(GpsIngestError) as exc_lat:
        validate_coordinates(True, 77.0)
    assert exc_lat.value.health is GpsHealth.LOCATION_UNAVAILABLE
    assert "booleans" in exc_lat.value.message

    with pytest.raises(GpsIngestError) as exc_lon:
        validate_coordinates(28.0, False)
    assert exc_lon.value.health is GpsHealth.LOCATION_UNAVAILABLE


def test_non_finite_coordinates_rejected():
    for bad in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(GpsIngestError):
            validate_coordinates(bad, 77.0)
        with pytest.raises(GpsIngestError):
            validate_coordinates(28.0, bad)


def test_boundary_coordinates_accepted(nav_state):
    lat, lon = validate_coordinates(-90.0, -180.0)
    assert lat == -90.0 and lon == -180.0

    lat, lon = validate_coordinates(90.0, 180.0)
    assert lat == 90.0 and lon == 180.0

    lat, lon = validate_coordinates(0.0, 0.0)
    assert lat == 0.0 and lon == 0.0


def test_out_of_range_coordinates_rejected():
    with pytest.raises(GpsIngestError):
        validate_coordinates(90.0001, 0.0)
    with pytest.raises(GpsIngestError):
        validate_coordinates(-90.0001, 0.0)
    with pytest.raises(GpsIngestError):
        validate_coordinates(0.0, 180.0001)
    with pytest.raises(GpsIngestError):
        validate_coordinates(0.0, -180.0001)


def test_accuracy_edge_cases(nav_state):
    # Valid accuracy
    payload = apply_gps_fix(nav_state, 28.0, 77.0, accuracy_m=12.5)
    assert payload["gps_accuracy_m"] == 12.5
    assert nav_state.current_location.accuracy_m == 12.5

    # Negative accuracy treated as None
    payload = apply_gps_fix(nav_state, 28.0, 77.0, accuracy_m=-5.0)
    assert payload["gps_accuracy_m"] is None
    assert nav_state.current_location.accuracy_m is None

    # Boolean accuracy treated as None
    payload = apply_gps_fix(nav_state, 28.0, 77.0, accuracy_m=True)
    assert payload["gps_accuracy_m"] is None

    # Non-numeric accuracy treated as None
    payload = apply_gps_fix(nav_state, 28.0, 77.0, accuracy_m="invalid")
    assert payload["gps_accuracy_m"] is None


def test_permission_denied_fault(nav_state):
    payload = apply_gps_fault(
        nav_state,
        GpsHealth.PERMISSION_DENIED,
        "Location permission denied",
    )
    assert payload["gps_health"] == GpsHealth.PERMISSION_DENIED.value
    assert "denied" in (payload["gps_detail"] or "").lower()
    assert nav_state.status is NavigationStatus.IDLE


def test_gps_unavailable_fault(nav_state):
    payload = apply_gps_fault(
        nav_state,
        GpsHealth.GPS_UNAVAILABLE,
        "GPS provider disabled",
    )
    assert payload["gps_health"] == GpsHealth.GPS_UNAVAILABLE.value


def test_location_unavailable_fault(nav_state):
    payload = apply_gps_fault(
        nav_state,
        GpsHealth.LOCATION_UNAVAILABLE,
        "No location sample",
    )
    assert payload["gps_health"] == GpsHealth.LOCATION_UNAVAILABLE.value


def test_fault_name_parsing():
    assert health_from_name("PERMISSION_DENIED") is GpsHealth.PERMISSION_DENIED
    assert health_from_name("permission_denied") is GpsHealth.PERMISSION_DENIED
    assert health_from_name(" gps_unavailable ") is GpsHealth.GPS_UNAVAILABLE
    assert health_from_name("STALE") is GpsHealth.STALE
    assert health_from_name("ERROR") is GpsHealth.ERROR

    with pytest.raises(GpsIngestError):
        health_from_name("")
    with pytest.raises(GpsIngestError):
        health_from_name("UNKNOWN_FAULT")
    with pytest.raises(GpsIngestError):
        health_from_name("ACTIVE")
    with pytest.raises(GpsIngestError):
        health_from_name("NONE")


def test_recovery_from_fault_when_valid_fix_arrives(nav_state):
    apply_gps_fault(nav_state, GpsHealth.GPS_UNAVAILABLE, "GPS disabled")
    assert nav_state.gps_health is GpsHealth.GPS_UNAVAILABLE
    assert nav_state.gps_detail == "GPS disabled"

    payload = apply_gps_fix(nav_state, 28.6139, 77.2090, accuracy_m=3.0)
    assert nav_state.gps_health is GpsHealth.ACTIVE
    assert nav_state.gps_detail is None
    assert payload["gps_health"] == GpsHealth.ACTIVE.value
    assert payload["gps_detail"] is None
    assert payload["current_latitude"] == 28.6139


def test_stale_location_detected_after_timeout(nav_state):
    apply_gps_fix(nav_state, 28.61, 77.20, now=100.0)
    payload = gps_status_payload(nav_state, now=100.0 + STALE_AFTER_S + 1.0)
    assert payload["gps_stale"] is True
    assert payload["gps_health"] == GpsHealth.STALE.value
    assert payload["gps_age_ms"] > STALE_AFTER_S * 1000.0
    assert nav_state.current_location is not None


def test_state_reset_clears_gps_and_allows_reset_from_idle(nav_state):
    # Calling reset() while already IDLE must not throw
    nav_state.reset()
    assert nav_state.status is NavigationStatus.IDLE

    # Applying GPS then resetting clears GPS fields
    apply_gps_fix(nav_state, 28.6, 77.2, accuracy_m=5.0)
    assert nav_state.current_location is not None
    nav_state.reset()
    assert nav_state.current_location is None
    assert nav_state.gps_health is GpsHealth.NONE
    assert nav_state.gps_detail is None
    assert nav_state.gps_received_at is None


def test_session_location_source_reads_navigation_state(nav_state):
    source = SessionLocationSource(nav_state)
    assert isinstance(source, LocationSource)
    assert source.current_fix() is None
    apply_gps_fix(nav_state, 1.0, 2.0)
    fix = source.current_fix()
    assert fix is not None
    assert fix.latitude == 1.0
    assert fix.longitude == 2.0


def test_gps_ingest_does_not_modify_obstacle_command(nav_state):
    with globals.command_lock:
        original = dict(globals.latest_command)
        globals.latest_command.update({"left": 0, "front": 200, "right": 0, "back": 0})
        before = dict(globals.latest_command)
    try:
        apply_gps_fix(nav_state, 28.6, 77.2)
        apply_gps_fault(nav_state, GpsHealth.ERROR, "provider error")
        with globals.command_lock:
            after = dict(globals.latest_command)
    finally:
        with globals.command_lock:
            globals.latest_command.update(original)
    assert after == before
    assert after["front"] == 200


def test_gps_http_ingest_updates_session():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from navigation.routes import router

    session.reset_session()
    app = fastapi.FastAPI()
    app.include_router(router)
    client = TestClient(app)

    missing = client.post("/nav/gps", json={"latitude": 28.6})
    assert missing.status_code == 422
    assert missing.json()["gps_health"] == GpsHealth.LOCATION_UNAVAILABLE.value

    ok = client.post(
        "/nav/gps",
        json={"latitude": 28.6139, "longitude": 77.2090, "accuracy_m": 3.0},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert body["current_latitude"] == 28.6139
    assert body["gps_health"] == GpsHealth.ACTIVE.value

    denied = client.post(
        "/nav/gps/fault",
        json={"health": "PERMISSION_DENIED", "message": "denied by user"},
    )
    assert denied.status_code == 200
    assert denied.json()["gps_health"] == GpsHealth.PERMISSION_DENIED.value

    status = client.get("/nav/status")
    assert status.status_code == 200
    assert status.json()["current_longitude"] == 77.2090

    cmd = client.get("/cmd")
    assert cmd.status_code == 404

    session.reset_session()
