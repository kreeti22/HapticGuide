"""
test_navigation_gps.py
----------------------
Phase 2: GPS ingest into navigation state.

No OSM, OSRM, Groq, or haptic playback.
HTTP tests skip if FastAPI is not installed.
"""

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


def test_stale_location_detected_after_timeout(nav_state):
    apply_gps_fix(nav_state, 28.61, 77.20, now=100.0)
    payload = gps_status_payload(nav_state, now=100.0 + STALE_AFTER_S + 1.0)
    assert payload["gps_stale"] is True
    assert payload["gps_health"] == GpsHealth.STALE.value
    assert payload["gps_age_ms"] > STALE_AFTER_S * 1000.0
    assert nav_state.current_location is not None


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
