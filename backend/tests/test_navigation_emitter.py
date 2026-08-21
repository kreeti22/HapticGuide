"""
test_navigation_emitter.py
--------------------------
Phase 6: Navigation haptic pulse emitter and obstacle mixer integration tests.

Verifies:
  - Exact pulse counts:
      * NAVIGATION_START: exactly 3 pulses on belt-left, belt-right, and phone-front
      * NAVIGATION_LEFT: exactly 2 pulses on belt-left
      * NAVIGATION_RIGHT: exactly 2 pulses on belt-right
      * NAVIGATION_FRONT: exactly 2 pulses on phone-front
      * NAVIGATION_ARRIVAL: placeholder event
  - Navigation NEVER sets ESP32 'front' or 'back'
  - Deduplication:
      * Same maneuver step does NOT emit repeated pulses on subsequent GPS updates
      * NAVIGATION_START emits only once per navigation session
  - Mixer priority:
      * Obstacle has absolute priority on occupied belt axes
      * Navigation operates on unoccupied belt axes
      * Phone-front remains independent of ESP32 belt axes
  - No hardware dependencies or physical vibration side effects in unit tests.
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest

import globals
from navigation import session
from navigation.contract import (
    NAVIGATION_EVENT_SPECS,
    NavigationEventType,
    NavigationTarget,
    mix_obstacle_and_navigation,
)
from navigation.emitter import (
    ActivePulseSequence,
    NavigationHapticEmitter,
    event_for_maneuver_code,
    get_mixed_command,
)
from navigation.follower import RouteProgress
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
def nav_emitter():
    state = NavigationState()
    emitter = NavigationHapticEmitter(state=state)
    return emitter


# ---------------------------------------------------------------------------
# Maneuver Code Mapping Tests
# ---------------------------------------------------------------------------

def test_event_for_maneuver_code_mappings():
    assert event_for_maneuver_code("LEFT") is NavigationEventType.LEFT
    assert event_for_maneuver_code("left") is NavigationEventType.LEFT
    assert event_for_maneuver_code("RIGHT") is NavigationEventType.RIGHT
    assert event_for_maneuver_code("right") is NavigationEventType.RIGHT
    assert event_for_maneuver_code("STRAIGHT") is NavigationEventType.FRONT
    assert event_for_maneuver_code("FRONT") is NavigationEventType.FRONT
    assert event_for_maneuver_code("ARRIVAL") is NavigationEventType.ARRIVAL
    assert event_for_maneuver_code("ARRIVE") is NavigationEventType.ARRIVAL
    assert event_for_maneuver_code(None) is None
    assert event_for_maneuver_code("") is None


# ---------------------------------------------------------------------------
# Pulse Count and Target Verification Tests
# ---------------------------------------------------------------------------

def test_navigation_start_exact_pulse_counts_and_targets(nav_emitter):
    """
    NAVIGATION_START:
    - Exactly 3 pulses on belt-left, belt-right, and phone-front
    - Duration = (3 * 80ms on) + (2 * 80ms off) = 400ms (0.400s)
    """
    t0 = 100.0
    seq = nav_emitter.play_event(NavigationEventType.START, now=t0)

    assert seq.pulse_count == 3
    assert NavigationTarget.BELT_LEFT in seq.targets
    assert NavigationTarget.BELT_RIGHT in seq.targets
    assert NavigationTarget.PHONE_FRONT in seq.targets
    assert round(seq.duration_s, 3) == 0.400

    # Pulse 1 (t0 + 40ms): ON
    p1 = seq.get_target_pwm(t0 + 0.040)
    assert p1["left"] == 255
    assert p1["right"] == 255
    assert p1["phone"] == 255
    assert "front" not in p1 or p1.get("front", 0) == 0
    assert "back" not in p1 or p1.get("back", 0) == 0

    # Gap 1 (t0 + 120ms): OFF
    g1 = seq.get_target_pwm(t0 + 0.120)
    assert g1["left"] == 0 and g1["right"] == 0 and g1["phone"] == 0

    # Pulse 2 (t0 + 200ms): ON
    p2 = seq.get_target_pwm(t0 + 0.200)
    assert p2["left"] == 255 and p2["right"] == 255 and p2["phone"] == 255

    # Gap 2 (t0 + 280ms): OFF
    g2 = seq.get_target_pwm(t0 + 0.280)
    assert g2["left"] == 0 and g2["right"] == 0 and g2["phone"] == 0

    # Pulse 3 (t0 + 360ms): ON
    p3 = seq.get_target_pwm(t0 + 0.360)
    assert p3["left"] == 255 and p3["right"] == 255 and p3["phone"] == 255

    # After completion (t0 + 420ms): OFF
    end = seq.get_target_pwm(t0 + 0.420)
    assert end["left"] == 0 and end["right"] == 0 and end["phone"] == 0


def test_navigation_left_exact_pulse_counts_and_targets(nav_emitter):
    """
    NAVIGATION_LEFT:
    - Exactly 2 pulses on belt-left ONLY
    - Duration = (2 * 80ms on) + (1 * 80ms off) = 240ms (0.240s)
    """
    t0 = 100.0
    seq = nav_emitter.play_event(NavigationEventType.LEFT, now=t0)

    assert seq.pulse_count == 2
    assert seq.targets == (NavigationTarget.BELT_LEFT,)
    assert round(seq.duration_s, 3) == 0.240

    # Pulse 1 (t0 + 40ms): ON on left only
    p1 = seq.get_target_pwm(t0 + 0.040)
    assert p1["left"] == 255
    assert p1["right"] == 0
    assert p1["phone"] == 0

    # Gap 1 (t0 + 120ms): OFF
    g1 = seq.get_target_pwm(t0 + 0.120)
    assert g1["left"] == 0 and g1["right"] == 0

    # Pulse 2 (t0 + 200ms): ON on left only
    p2 = seq.get_target_pwm(t0 + 0.200)
    assert p2["left"] == 255
    assert p2["right"] == 0
    assert p2["phone"] == 0

    # After completion (t0 + 260ms): OFF
    end = seq.get_target_pwm(t0 + 0.260)
    assert end["left"] == 0 and end["right"] == 0


def test_navigation_right_exact_pulse_counts_and_targets(nav_emitter):
    """
    NAVIGATION_RIGHT:
    - Exactly 2 pulses on belt-right ONLY
    - Duration = 240ms
    """
    t0 = 100.0
    seq = nav_emitter.play_event(NavigationEventType.RIGHT, now=t0)

    assert seq.pulse_count == 2
    assert seq.targets == (NavigationTarget.BELT_RIGHT,)
    assert round(seq.duration_s, 3) == 0.240

    # Pulse 1: ON on right only
    p1 = seq.get_target_pwm(t0 + 0.040)
    assert p1["right"] == 255
    assert p1["left"] == 0
    assert p1["phone"] == 0

    # Pulse 2: ON on right only
    p2 = seq.get_target_pwm(t0 + 0.200)
    assert p2["right"] == 255
    assert p2["left"] == 0


def test_navigation_front_exact_pulse_counts_and_targets(nav_emitter):
    """
    NAVIGATION_FRONT:
    - Exactly 2 pulses on phone-front ONLY (smartphone)
    - Never sets belt left, right, front, or back
    """
    t0 = 100.0
    seq = nav_emitter.play_event(NavigationEventType.FRONT, now=t0)

    assert seq.pulse_count == 2
    assert seq.targets == (NavigationTarget.PHONE_FRONT,)
    assert round(seq.duration_s, 3) == 0.240

    # Pulse 1: ON on phone only
    p1 = seq.get_target_pwm(t0 + 0.040)
    assert p1["phone"] == 255
    assert p1["left"] == 0
    assert p1["right"] == 0

    # Pulse 2: ON on phone only
    p2 = seq.get_target_pwm(t0 + 0.200)
    assert p2["phone"] == 255
    assert p2["left"] == 0
    assert p2["right"] == 0


# ---------------------------------------------------------------------------
# Protection: Navigation NEVER writes ESP32 front or back
# ---------------------------------------------------------------------------

def test_navigation_never_writes_esp32_front_or_back(nav_emitter):
    t0 = 100.0

    for event_type in (
        NavigationEventType.START,
        NavigationEventType.LEFT,
        NavigationEventType.RIGHT,
        NavigationEventType.FRONT,
        NavigationEventType.ARRIVAL,
    ):
        seq = nav_emitter.play_event(event_type, now=t0)
        pwm = seq.get_target_pwm(t0 + 0.040)

        # Navigation output dictionary must NEVER contain non-zero front or back
        assert pwm.get("front", 0) == 0
        assert pwm.get("back", 0) == 0


# ---------------------------------------------------------------------------
# Mixer Priority Tests
# ---------------------------------------------------------------------------

def test_obstacle_priority_on_occupied_left_belt_axis(nav_emitter):
    t0 = 100.0
    nav_emitter.play_event(NavigationEventType.LEFT, now=t0)

    # Obstacle has active obstacle on left (PWM = 190)
    obstacle_cmd = {"left": 190, "front": 0, "right": 0, "back": 0}

    # At pulse 1 ON time (t0 + 40ms)
    mixed = nav_emitter.mix_with_obstacle(obstacle_cmd, now=t0 + 0.040)

    # Obstacle 190 wins over navigation 255!
    assert mixed["left"] == 190
    assert mixed["right"] == 0
    assert mixed["front"] == 0
    assert mixed["back"] == 0


def test_obstacle_priority_on_occupied_right_belt_axis(nav_emitter):
    t0 = 100.0
    nav_emitter.play_event(NavigationEventType.RIGHT, now=t0)

    # Obstacle has active obstacle on right (PWM = 160)
    obstacle_cmd = {"left": 0, "front": 0, "right": 160, "back": 0}

    mixed = nav_emitter.mix_with_obstacle(obstacle_cmd, now=t0 + 0.040)

    # Obstacle 160 wins over navigation 255!
    assert mixed["right"] == 160
    assert mixed["left"] == 0


def test_navigation_operates_on_unoccupied_belt_axis(nav_emitter):
    t0 = 100.0
    nav_emitter.play_event(NavigationEventType.RIGHT, now=t0)

    # Obstacle has active obstacle on FRONT (180), but RIGHT is unoccupied (0)
    obstacle_cmd = {"left": 0, "front": 180, "right": 0, "back": 0}

    mixed = nav_emitter.mix_with_obstacle(obstacle_cmd, now=t0 + 0.040)

    # Front retains obstacle 180, right plays navigation 255!
    assert mixed["front"] == 180
    assert mixed["right"] == 255
    assert mixed["left"] == 0


def test_phone_front_navigation_independent_of_esp32_belt_axes(nav_emitter):
    t0 = 100.0
    nav_emitter.play_event(NavigationEventType.FRONT, now=t0)

    obstacle_cmd = {"left": 150, "front": 200, "right": 120, "back": 0}
    mixed = nav_emitter.mix_with_obstacle(obstacle_cmd, now=t0 + 0.040)

    # Belt axes retain all obstacle PWMs
    assert mixed["left"] == 150
    assert mixed["front"] == 200
    assert mixed["right"] == 120
    # Phone gets navigation 255 independently
    assert mixed["phone"] == 255


# ---------------------------------------------------------------------------
# Deduplication Tests
# ---------------------------------------------------------------------------

def test_navigation_start_emitted_only_once_per_session():
    state = NavigationState()
    state.status = NavigationStatus.NAVIGATING
    state.route_status = RouteStatus.ACTIVE
    emitter = NavigationHapticEmitter(state=state)

    progress = RouteProgress(
        active=True,
        current_step_index=0,
        next_maneuver="STRAIGHT",
        is_maneuver_imminent=False,
    )

    # First progress update emits START
    event1 = emitter.evaluate_and_emit(state, progress, now=100.0)
    assert event1 is NavigationEventType.START

    # Subsequent progress updates do NOT emit START again
    event2 = emitter.evaluate_and_emit(state, progress, now=101.0)
    assert event2 is None

    event3 = emitter.evaluate_and_emit(state, progress, now=102.0)
    assert event3 is None

    history = emitter.get_event_history()
    assert len(history) == 1
    assert history[0][1] is NavigationEventType.START


def test_maneuver_event_deduplicated_per_route_step():
    state = NavigationState()
    state.status = NavigationStatus.NAVIGATING
    state.route_status = RouteStatus.ACTIVE
    emitter = NavigationHapticEmitter(state=state)

    # Trigger START first
    emitter.evaluate_and_emit(
        state,
        RouteProgress(active=True, current_step_index=0, next_maneuver="STRAIGHT", is_maneuver_imminent=False),
        now=100.0,
    )

    # Step 0 approaching RIGHT turn (45m away)
    p_step0_imminent = RouteProgress(
        active=True,
        current_step_index=0,
        next_maneuver="RIGHT",
        distance_to_next_m=45.0,
        is_maneuver_imminent=True,
    )

    # First GPS update in trigger zone emits NAVIGATION_RIGHT
    ev_turn = emitter.evaluate_and_emit(state, p_step0_imminent, now=105.0)
    assert ev_turn is NavigationEventType.RIGHT

    # Subsequent GPS updates while still on Step 0 (e.g. 40m, 35m, 30m away) must NOT re-emit!
    p_step0_40m = RouteProgress(
        active=True,
        current_step_index=0,
        next_maneuver="RIGHT",
        distance_to_next_m=40.0,
        is_maneuver_imminent=True,
    )
    assert emitter.evaluate_and_emit(state, p_step0_40m, now=106.0) is None

    p_step0_30m = RouteProgress(
        active=True,
        current_step_index=0,
        next_maneuver="RIGHT",
        distance_to_next_m=30.0,
        is_maneuver_imminent=True,
    )
    assert emitter.evaluate_and_emit(state, p_step0_30m, now=107.0) is None

    # When user completes turn and step advances to Step 1 (approaching LEFT turn)
    p_step1_imminent = RouteProgress(
        active=True,
        current_step_index=1,
        next_maneuver="LEFT",
        distance_to_next_m=42.0,
        is_maneuver_imminent=True,
    )

    # Step 1 emits NAVIGATION_LEFT
    ev_step1 = emitter.evaluate_and_emit(state, p_step1_imminent, now=110.0)
    assert ev_step1 is NavigationEventType.LEFT

    # Subsequent updates on Step 1 do NOT re-emit
    assert emitter.evaluate_and_emit(state, p_step1_imminent, now=111.0) is None


# ---------------------------------------------------------------------------
# GET /cmd Integration via get_mixed_command
# ---------------------------------------------------------------------------

def test_get_mixed_command_preserves_obstacle_and_adds_nav_pulses():
    session.reset_session()
    state = session.get_state()
    state.status = NavigationStatus.NAVIGATING
    state.route_status = RouteStatus.ACTIVE

    # Set obstacle state
    with globals.command_lock:
        orig = dict(globals.latest_command)
        globals.latest_command.update({"left": 0, "front": 190, "right": 0, "back": 0})

    try:
        from navigation.emitter import get_emitter
        emitter = get_emitter(state)
        emitter.reset()

        # Emit NAVIGATION_LEFT at t0 = 100.0
        t0 = 100.0
        emitter.play_event(NavigationEventType.LEFT, now=t0)

        # Pulse 1 ON (100.040s)
        cmd_on = get_mixed_command(dict(globals.latest_command), now=t0 + 0.040)
        assert cmd_on["left"] == 255  # Navigation left active
        assert cmd_on["front"] == 190  # Obstacle front preserved!
        assert cmd_on["right"] == 0
        assert cmd_on["back"] == 0
        assert "phone" not in cmd_on  # Stripped from ESP32 4-axis command

        # Gap 1 OFF (100.120s)
        cmd_gap = get_mixed_command(dict(globals.latest_command), now=t0 + 0.120)
        assert cmd_gap["left"] == 0
        assert cmd_gap["front"] == 190

        # Pulse 2 ON (100.200s)
        cmd_p2 = get_mixed_command(dict(globals.latest_command), now=t0 + 0.200)
        assert cmd_p2["left"] == 255
        assert cmd_p2["front"] == 190

        # After sequence (100.300s)
        cmd_end = get_mixed_command(dict(globals.latest_command), now=t0 + 0.300)
        assert cmd_end["left"] == 0
        assert cmd_end["front"] == 190
    finally:
        with globals.command_lock:
            globals.latest_command.update(orig)
        session.reset_session()
