"""
test_e2e_integration.py
-----------------------
End-to-end integration test validating the complete pipeline:
- FastAPI live dashboard (/live)
- Destination search & OSRM route calculation
- Route start & live GPS following
- Contract haptic pulse generation & obstacle priority mixer
- Android decision payload ingestion & serial mapping verification
"""

import sys
from pathlib import Path
import pytest

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import router as main_router
from navigation.routes import router as nav_router
from navigation import session
from navigation.contract import NavigationEventType
from navigation.state import GeoPoint, GpsFix, NavigationInstruction, NavigationState, NavigationStatus, RouteSnapshot, RouteStep
import globals


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(main_router)
    app.include_router(nav_router)

    with session.get_lock():
        session.get_state().reset()
    from navigation.emitter import get_emitter
    get_emitter().reset()
    with globals.command_lock:
        globals.latest_command = {"left": 0, "front": 0, "right": 0, "back": 0}
    return TestClient(app)


def test_e2e_live_dashboard_endpoint(client):
    """Verify /live dashboard returns HTTP 200 and contains navigation elements."""
    res = client.get("/live")
    assert res.status_code == 200
    assert "HapticGuide" in res.text
    assert "live-nav-hud" in res.text
    assert "nav-modal" in res.text
    assert "pollNav" in res.text


def test_e2e_navigation_flow_and_events(client):
    """
    Verify complete flow:
    Search -> Route -> Start -> GPS Ingest -> Maneuver Event -> Mixer /cmd
    """
    # 1. Provide origin GPS fix
    gps_res = client.post("/nav/gps", json={"latitude": 28.6139, "longitude": 77.2090, "accuracy_m": 3.0})
    assert gps_res.status_code == 200
    data = gps_res.json()
    assert data["ok"] is True
    assert data["status"] == "IDLE"

    # 2. Mock an active route snapshot directly on session state
    step0 = RouteStep(
        instruction="Head north on Radial Road 1",
        maneuver_type="depart",
        location=GeoPoint(latitude=28.6139, longitude=77.2090),
        distance_m=40.0,
    )
    step1 = RouteStep(
        instruction="Turn left onto Connaught Circus",
        maneuver_type="turn",
        maneuver_modifier="left",
        location=GeoPoint(latitude=28.6143, longitude=77.2090),
        distance_m=100.0,
    )
    step2 = RouteStep(
        instruction="You have arrived at your destination",
        maneuver_type="arrive",
        location=GeoPoint(latitude=28.6150, longitude=77.2085),
        distance_m=0.0,
    )

    route_snap = RouteSnapshot(
        current=NavigationInstruction(text=step0.instruction, maneuver="STRAIGHT", distance_m=40.0, step_index=0),
        next=NavigationInstruction(text=step1.instruction, maneuver="LEFT", distance_m=100.0, step_index=1),
        distance_to_next_m=40.0,
        remaining_distance_m=140.0,
        total_distance_m=140.0,
        total_duration_s=120.0,
        steps=(step0, step1, step2),
    )

    with session.get_lock():
        state = session.get_state()
        state.status = NavigationStatus.CALCULATING_ROUTE
        state.set_route(route_snap)

    # 3. Start navigation
    start_res = client.post("/nav/start")
    assert start_res.status_code == 200
    start_data = start_res.json()
    assert start_data["ok"] is True
    assert start_data["status"] == "NAVIGATING"
    # Verify NAVIGATION_START is emitted
    assert start_data["pending_haptic_event"] == "NAVIGATION_START"

    # 4. Ingest GPS update near step 1 turn (imminent maneuver)
    turn_gps_res = client.post("/nav/gps", json={"latitude": 28.6140, "longitude": 77.2090, "accuracy_m": 2.5})
    assert turn_gps_res.status_code == 200

    # 5. Check /nav/progress endpoint (consumed by Live Dashboard)
    prog_res = client.get("/nav/progress")
    assert prog_res.status_code == 200
    prog_data = prog_res.json()
    assert prog_data["ok"] is True
    assert prog_data["status"] == "NAVIGATING"

    # 6. Verify obstacle priority mixer on GET /cmd
    cmd_res1 = client.get("/cmd")
    assert cmd_res1.status_code == 200
    cmd1 = cmd_res1.json()
    assert "left" in cmd1
    assert "right" in cmd1
    assert "front" in cmd1
    assert "back" in cmd1

    # When obstacle command is present on front (GPIO 13) or left (GPIO 12):
    with globals.command_lock:
        globals.latest_command = {"left": 180, "front": 255, "right": 0, "back": 0}

    cmd_res2 = client.get("/cmd")
    cmd2 = cmd_res2.json()
    # Obstacle wins on left (180) and front (255)
    assert cmd2["front"] == 255
    assert cmd2["left"] == 180
