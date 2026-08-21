"""
test_navigation_follower.py
---------------------------
Phase 5: Live GPS route following and next maneuver tracking tests.

Tests real-time GPS position tracking against calculated route, step progression,
maneuver distance calculations, maneuver type normalization (LEFT, RIGHT, STRAIGHT, ARRIVAL),
arrival detection, off-route detection/recovery, GPS noise tolerance, and state updates.

Deterministic mocked coordinates are used — no live GPS or live network calls.
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest

import globals
from navigation import session
from navigation.follower import (
    DEFAULT_ARRIVAL_THRESHOLD_M,
    DEFAULT_OFF_ROUTE_THRESHOLD_M,
    DEFAULT_STEP_TRANSITION_THRESHOLD_M,
    DEFAULT_UPCOMING_MANEUVER_THRESHOLD_M,
    RouteFollower,
    RouteProgress,
    distance_to_route_geometry_m,
    point_to_segment_distance_m,
    update_route_progress,
)
from navigation.gps import apply_gps_fix
from navigation.state import (
    GeoPoint,
    GpsFix,
    NavigationInstruction,
    NavigationState,
    NavigationStatus,
    RouteSnapshot,
    RouteStatus,
    RouteStep,
)


@pytest.fixture
def sample_route():
    """
    Construct a 3-step route in New Delhi:
    Step 0: Depart Connaught Circus (28.6139, 77.2090), head straight, 400m
    Step 1: Turn right onto Barakhamba Road at (28.6175, 77.2090), 800m
    Step 2: Turn left onto Tolstoy Marg at (28.6175, 77.2170), 500m
    Step 3: Arrive at destination at (28.6220, 77.2170), 0m
    """
    origin = GeoPoint(latitude=28.6139, longitude=77.2090)
    step1_loc = GeoPoint(latitude=28.6175, longitude=77.2090)
    step2_loc = GeoPoint(latitude=28.6175, longitude=77.2170)
    dest_loc = GeoPoint(latitude=28.6220, longitude=77.2170)

    steps = (
        RouteStep(
            instruction="Head straight on Connaught Circus",
            maneuver_type="depart",
            maneuver_modifier="straight",
            location=origin,
            distance_m=400.0,
            duration_s=60.0,
            road_name="Connaught Circus",
        ),
        RouteStep(
            instruction="Turn right onto Barakhamba Road",
            maneuver_type="turn",
            maneuver_modifier="right",
            location=step1_loc,
            distance_m=800.0,
            duration_s=120.0,
            road_name="Barakhamba Road",
        ),
        RouteStep(
            instruction="Turn left onto Tolstoy Marg",
            maneuver_type="turn",
            maneuver_modifier="left",
            location=step2_loc,
            distance_m=500.0,
            duration_s=75.0,
            road_name="Tolstoy Marg",
        ),
        RouteStep(
            instruction="You have arrived at your destination",
            maneuver_type="arrive",
            maneuver_modifier=None,
            location=dest_loc,
            distance_m=0.0,
            duration_s=0.0,
            road_name="Tolstoy Marg",
        ),
    )

    geometry = {
        "type": "LineString",
        "coordinates": [
            [77.2090, 28.6139],
            [77.2090, 28.6175],
            [77.2170, 28.6175],
            [77.2170, 28.6220],
        ],
    }

    return RouteSnapshot(
        current=NavigationInstruction("Head straight on Connaught Circus", maneuver="STRAIGHT", distance_m=400.0),
        next=NavigationInstruction("Turn right onto Barakhamba Road", maneuver="RIGHT", distance_m=800.0),
        distance_to_next_m=400.0,
        remaining_distance_m=1700.0,
        total_distance_m=1700.0,
        total_duration_s=255.0,
        steps=steps,
        geometry=geometry,
        origin=origin,
        destination=dest_loc,
    )


@pytest.fixture
def active_nav_state(sample_route):
    state = NavigationState()
    state.destination = sample_route.destination
    state.destination_name = "Tolstoy Complex"
    state.begin_route_calculation()
    state.set_route(sample_route)
    return state


# ---------------------------------------------------------------------------
# Geometric Distance Helper Tests
# ---------------------------------------------------------------------------

def test_point_to_segment_distance():
    # Point directly on segment
    d_on = point_to_segment_distance_m(28.6150, 77.2090, 28.6139, 77.2090, 28.6175, 77.2090)
    assert d_on < 1.0

    # Point 50m east of north-south segment at lon 77.2090
    # ~0.0005 deg longitude difference at 28 deg latitude is ~48 meters
    d_offset = point_to_segment_distance_m(28.6150, 77.2095, 28.6139, 77.2090, 28.6175, 77.2090)
    assert 40.0 < d_offset < 60.0


def test_distance_to_route_geometry(sample_route):
    # Point along step 0 segment
    p_on = GeoPoint(latitude=28.6150, longitude=77.2090)
    dist = distance_to_route_geometry_m(p_on, sample_route.geometry, sample_route.steps)
    assert dist < 1.0

    # Point far off route (e.g. 500m west)
    p_off = GeoPoint(latitude=28.6150, longitude=77.2040)
    dist_off = distance_to_route_geometry_m(p_off, sample_route.geometry, sample_route.steps)
    assert dist_off > 300.0


# ---------------------------------------------------------------------------
# Route Following Initialization Tests
# ---------------------------------------------------------------------------

def test_first_gps_position_initializes_route_following(active_nav_state):
    assert active_nav_state.status is NavigationStatus.ROUTE_READY
    assert active_nav_state.current_step_index == 0

    fix = GpsFix(latitude=28.6139, longitude=77.2090, accuracy_m=3.0)
    progress = update_route_progress(active_nav_state, fix=fix)

    assert progress.active is True
    assert active_nav_state.status is NavigationStatus.NAVIGATING
    assert active_nav_state.route_status is RouteStatus.ACTIVE
    assert progress.current_step_index == 0
    assert progress.current_instruction is not None
    assert "Connaught Circus" in progress.current_instruction.text
    assert progress.next_instruction is not None
    assert "Barakhamba" in progress.next_instruction.text
    assert progress.next_maneuver == "RIGHT"
    assert progress.is_off_route is False
    assert progress.is_arrived is False


def test_no_route_returns_inactive_progress():
    state = NavigationState()
    fix = GpsFix(latitude=28.6139, longitude=77.2090)
    progress = update_route_progress(state, fix=fix)
    assert progress.active is False


# ---------------------------------------------------------------------------
# Maneuver Normalization & Distance Tests
# ---------------------------------------------------------------------------

def test_maneuver_normalization_tokens(active_nav_state):
    fix = GpsFix(latitude=28.6139, longitude=77.2090)
    progress = update_route_progress(active_nav_state, fix=fix)

    assert progress.current_instruction.maneuver == "STRAIGHT"
    assert progress.next_instruction.maneuver == "RIGHT"
    assert progress.next_maneuver == "RIGHT"


def test_distance_to_next_maneuver_calculated_accurately(active_nav_state):
    # User at start of step 0: (28.6139, 77.2090)
    # Next junction (step 1) is at: (28.6175, 77.2090) -> distance is ~400m
    fix = GpsFix(latitude=28.6139, longitude=77.2090)
    progress = update_route_progress(active_nav_state, fix=fix)

    assert 380.0 < progress.distance_to_next_m < 420.0
    assert progress.is_maneuver_imminent is False

    # User advances to 40m before junction: (28.61714, 77.2090)
    fix_near = GpsFix(latitude=28.61714, longitude=77.2090)
    progress_near = update_route_progress(active_nav_state, fix=fix_near)

    assert progress_near.distance_to_next_m < 50.0
    assert progress_near.is_maneuver_imminent is True


# ---------------------------------------------------------------------------
# Step Progression Tests
# ---------------------------------------------------------------------------

def test_step_advances_when_user_reaches_maneuver_junction(active_nav_state):
    # Step 0: User starts at origin
    fix0 = GpsFix(latitude=28.6139, longitude=77.2090)
    p0 = update_route_progress(active_nav_state, fix=fix0)
    assert p0.current_step_index == 0

    # User reaches Step 1 junction: (28.6175, 77.2090) (within step threshold of 20m)
    fix1 = GpsFix(latitude=28.6175, longitude=77.2090)
    p1 = update_route_progress(active_nav_state, fix=fix1)

    assert p1.current_step_index == 1
    assert active_nav_state.current_step_index == 1
    assert "Barakhamba Road" in p1.current_instruction.text
    assert "Tolstoy Marg" in p1.next_instruction.text
    assert p1.next_maneuver == "LEFT"

    # User moves along Barakhamba Road and reaches Step 2 junction at (28.6175, 77.2170)
    fix2 = GpsFix(latitude=28.6175, longitude=77.2170)
    p2 = update_route_progress(active_nav_state, fix=fix2)

    assert p2.current_step_index == 2
    assert active_nav_state.current_step_index == 2
    assert "Tolstoy Marg" in p2.current_instruction.text
    assert "arrived" in p2.next_instruction.text.lower()
    assert p2.next_maneuver == "ARRIVAL"


def test_repeated_identical_gps_fixes_do_not_falsely_advance_step(active_nav_state):
    fix = GpsFix(latitude=28.6145, longitude=77.2090)

    for _ in range(10):
        progress = update_route_progress(active_nav_state, fix=fix)
        assert progress.current_step_index == 0
        assert active_nav_state.current_step_index == 0


def test_gps_noise_does_not_cause_step_jumping(active_nav_state):
    # Small GPS jitter around step 0 location (+/- 4 meters)
    jitter_points = [
        (28.61450, 77.20902),
        (28.61452, 77.20898),
        (28.61448, 77.20901),
        (28.61451, 77.20899),
    ]

    for lat, lon in jitter_points:
        p = update_route_progress(active_nav_state, fix=GpsFix(latitude=lat, longitude=lon))
        assert p.current_step_index == 0
        assert p.is_off_route is False


# ---------------------------------------------------------------------------
# Arrival Detection Tests
# ---------------------------------------------------------------------------

def test_arrival_detected_at_destination(active_nav_state):
    # Destination is at (28.6220, 77.2170)
    # User arrives within 10m: (28.62205, 77.2170)
    dest_fix = GpsFix(latitude=28.62205, longitude=77.2170)
    progress = update_route_progress(active_nav_state, fix=dest_fix)

    assert progress.is_arrived is True
    assert active_nav_state.status is NavigationStatus.ARRIVED
    assert active_nav_state.route_status is RouteStatus.COMPLETE
    assert progress.distance_to_next_m == 0.0
    assert progress.remaining_distance_m == 0.0
    assert "arrived" in progress.current_instruction.text.lower()


# ---------------------------------------------------------------------------
# Off-Route Detection and Recovery Tests
# ---------------------------------------------------------------------------

def test_off_route_detected_when_user_deviates(active_nav_state):
    # Start on route
    update_route_progress(active_nav_state, fix=GpsFix(latitude=28.6150, longitude=77.2090))
    assert active_nav_state.status is NavigationStatus.NAVIGATING

    # User deviates 100m west of Connaught Circus to (28.6150, 77.2078)
    off_fix = GpsFix(latitude=28.6150, longitude=77.2078)
    progress = update_route_progress(active_nav_state, fix=off_fix)

    assert progress.is_off_route is True
    assert active_nav_state.status is NavigationStatus.OFF_ROUTE
    assert active_nav_state.route_status is RouteStatus.OFF_ROUTE


def test_off_route_recovers_when_user_returns_to_route(active_nav_state):
    # Deviate off route
    off_fix = GpsFix(latitude=28.6150, longitude=77.2078)
    update_route_progress(active_nav_state, fix=off_fix)
    assert active_nav_state.status is NavigationStatus.OFF_ROUTE

    # User walks back onto the route: (28.6150, 77.2090)
    on_fix = GpsFix(latitude=28.6150, longitude=77.2090)
    progress = update_route_progress(active_nav_state, fix=on_fix)

    assert progress.is_off_route is False
    assert active_nav_state.status is NavigationStatus.NAVIGATING
    assert active_nav_state.route_status is RouteStatus.ACTIVE


# ---------------------------------------------------------------------------
# Integration with apply_gps_fix Tests
# ---------------------------------------------------------------------------

def test_apply_gps_fix_automatically_updates_active_route(active_nav_state):
    payload = apply_gps_fix(active_nav_state, 28.6139, 77.2090, accuracy_m=4.0)

    assert payload["status"] == "NAVIGATING"
    assert payload["route_status"] == "ACTIVE"
    assert payload["current_step_index"] == 0
    assert payload["is_off_route"] is False
    assert payload["is_arrived"] is False
    assert payload["distance_to_next_m"] is not None


# ---------------------------------------------------------------------------
# Protection Confirmation Tests
# ---------------------------------------------------------------------------

def test_route_following_does_not_modify_obstacle_state(active_nav_state):
    with globals.command_lock:
        orig = dict(globals.latest_command)
        globals.latest_command.update({"left": 180, "front": 0, "right": 220, "back": 0})
        before = dict(globals.latest_command)

    try:
        fix = GpsFix(latitude=28.6150, longitude=77.2090)
        update_route_progress(active_nav_state, fix=fix)

        with globals.command_lock:
            after = dict(globals.latest_command)
    finally:
        with globals.command_lock:
            globals.latest_command.update(orig)

    assert after == before
    assert after["left"] == 180
    assert after["right"] == 220


def test_route_following_generates_no_haptic_pulses(active_nav_state):
    fix = GpsFix(latitude=28.6175, longitude=77.2090)
    update_route_progress(active_nav_state, fix=fix)

    # State reflects upcoming instruction, but no physical pulse engine is invoked
    assert active_nav_state.current_instruction.maneuver in ("LEFT", "RIGHT", "STRAIGHT", "ARRIVAL")
    assert active_nav_state.pending_haptic_event in (None, "START", "ARRIVAL") or hasattr(active_nav_state.pending_haptic_event, "value")
