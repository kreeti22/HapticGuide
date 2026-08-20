"""
test_navigation_contract.py
---------------------------
Phase 0: navigation event contract and mixer specification tests.

Does not call Groq, OSM, OSRM, GPS, or the live obstacle pipeline.
mix_obstacle_and_navigation is the specified mixer behaviour for later wiring.
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from navigation.contract import (
    BELT_AXES,
    NAVIGATION_EVENT_SPECS,
    NAVIGATION_OUTPUT_KEYS,
    NavigationEventType,
    NavigationTarget,
    empty_navigation_command,
    empty_obstacle_command,
    mix_obstacle_and_navigation,
    navigation_command_for_event,
)


def test_navigation_event_specs_have_type_targets_count_and_timing():
    required = (
        NavigationEventType.START,
        NavigationEventType.LEFT,
        NavigationEventType.RIGHT,
        NavigationEventType.FRONT,
        NavigationEventType.ARRIVAL,
    )
    for event_type in required:
        spec = NAVIGATION_EVENT_SPECS[event_type]
        assert spec.event_type is event_type
        assert isinstance(spec.targets, tuple)
        assert spec.pulse_count >= 0
        assert spec.pulse_on_ms >= 0
        assert spec.pulse_off_ms >= 0


def test_navigation_start_is_three_pulses_on_all_nav_outputs():
    spec = NAVIGATION_EVENT_SPECS[NavigationEventType.START]
    assert spec.pulse_count == 3
    assert spec.targets == (
        NavigationTarget.BELT_LEFT,
        NavigationTarget.BELT_RIGHT,
        NavigationTarget.PHONE_FRONT,
    )


def test_navigation_left_is_two_pulses_on_left_belt():
    spec = NAVIGATION_EVENT_SPECS[NavigationEventType.LEFT]
    assert spec.pulse_count == 2
    assert spec.targets == (NavigationTarget.BELT_LEFT,)


def test_navigation_right_is_two_pulses_on_right_belt():
    spec = NAVIGATION_EVENT_SPECS[NavigationEventType.RIGHT]
    assert spec.pulse_count == 2
    assert spec.targets == (NavigationTarget.BELT_RIGHT,)


def test_navigation_front_is_two_pulses_on_phone_not_esp32_front():
    spec = NAVIGATION_EVENT_SPECS[NavigationEventType.FRONT]
    assert spec.pulse_count == 2
    assert spec.targets == (NavigationTarget.PHONE_FRONT,)
    assert NavigationTarget.BELT_LEFT not in spec.targets
    assert NavigationTarget.BELT_RIGHT not in spec.targets


def test_navigation_arrival_is_placeholder():
    spec = NAVIGATION_EVENT_SPECS[NavigationEventType.ARRIVAL]
    assert spec.implemented is False
    assert spec.pulse_count == 0
    assert spec.targets == ()
    cmd = navigation_command_for_event(NavigationEventType.ARRIVAL)
    assert cmd == empty_navigation_command()


def test_navigation_command_schema_has_no_esp32_front_or_back():
    assert "front" not in NAVIGATION_OUTPUT_KEYS
    assert "back" not in NAVIGATION_OUTPUT_KEYS
    assert NAVIGATION_OUTPUT_KEYS == ("left", "right", "phone")
    for event_type in NavigationEventType:
        cmd = navigation_command_for_event(event_type)
        assert set(cmd.keys()) == {"left", "right", "phone"}
        assert "front" not in cmd
        assert "back" not in cmd


def test_obstacle_command_schema_is_unchanged_four_axis_belt():
    obstacle = empty_obstacle_command()
    assert tuple(obstacle.keys()) == BELT_AXES
    assert "phone" not in obstacle


# ---------------------------------------------------------------------------
# Mixer contract cases
# ---------------------------------------------------------------------------

def test_case_a_no_obstacle_navigation_left_allowed():
    mixed = mix_obstacle_and_navigation(
        empty_obstacle_command(),
        navigation_command_for_event(NavigationEventType.LEFT),
    )
    assert mixed["left"] == 255
    assert mixed["right"] == 0
    assert mixed["front"] == 0
    assert mixed["back"] == 0
    assert mixed["phone"] == 0


def test_case_b_no_obstacle_navigation_right_allowed():
    mixed = mix_obstacle_and_navigation(
        empty_obstacle_command(),
        navigation_command_for_event(NavigationEventType.RIGHT),
    )
    assert mixed["right"] == 255
    assert mixed["left"] == 0
    assert mixed["front"] == 0
    assert mixed["phone"] == 0


def test_case_c_no_obstacle_navigation_front_targets_phone_not_esp32_front():
    mixed = mix_obstacle_and_navigation(
        empty_obstacle_command(),
        navigation_command_for_event(NavigationEventType.FRONT),
    )
    assert mixed["phone"] == 255
    assert mixed["front"] == 0
    assert mixed["left"] == 0
    assert mixed["right"] == 0
    assert mixed["back"] == 0


def test_case_d_obstacle_left_wins_over_navigation_left():
    obstacle = {"left": 255, "front": 0, "right": 0, "back": 0}
    mixed = mix_obstacle_and_navigation(
        obstacle,
        navigation_command_for_event(NavigationEventType.LEFT),
    )
    assert mixed["left"] == 255
    assert mixed["left"] == obstacle["left"]
    assert mixed["phone"] == 0
    assert mixed["right"] == 0


def test_case_e_obstacle_right_wins_over_navigation_right():
    obstacle = {"left": 0, "front": 0, "right": 255, "back": 0}
    mixed = mix_obstacle_and_navigation(
        obstacle,
        navigation_command_for_event(NavigationEventType.RIGHT),
    )
    assert mixed["right"] == 255
    assert mixed["right"] == obstacle["right"]
    assert mixed["left"] == 0
    assert mixed["phone"] == 0


def test_case_f_obstacle_center_front_stays_authoritative_navigation_does_not_replace_belt_front():
    obstacle = {"left": 0, "front": 255, "right": 0, "back": 0}
    nav = navigation_command_for_event(NavigationEventType.FRONT)
    mixed = mix_obstacle_and_navigation(obstacle, nav)

    assert mixed["front"] == 255
    assert mixed["front"] == obstacle["front"]
    # Navigation FRONT is phone-only; it must not be copied onto ESP32 front.
    assert nav.get("front", 0) == 0
    assert mixed["phone"] == 255


def test_mixer_ignores_navigation_front_key_on_esp32_belt():
    """If a future caller mistakenly sets navigation['front'], belt front stays obstacle-only."""
    obstacle = empty_obstacle_command()
    mixed = mix_obstacle_and_navigation(
        obstacle,
        {"left": 0, "right": 0, "front": 255, "phone": 0},
    )
    assert mixed["front"] == 0
    assert mixed["phone"] == 0


def test_case_g_no_obstacle_navigation_start_allowed():
    mixed = mix_obstacle_and_navigation(
        empty_obstacle_command(),
        navigation_command_for_event(NavigationEventType.START),
    )
    assert mixed["left"] == 255
    assert mixed["right"] == 255
    assert mixed["phone"] == 255
    assert mixed["front"] == 0
    assert mixed["back"] == 0


def test_navigation_start_does_not_overwrite_active_obstacle_axes():
    obstacle = {"left": 255, "front": 0, "right": 0, "back": 0}
    mixed = mix_obstacle_and_navigation(
        obstacle,
        navigation_command_for_event(NavigationEventType.START),
    )
    assert mixed["left"] == 255
    assert mixed["right"] == 255
    assert mixed["phone"] == 255
    assert mixed["front"] == 0


def test_mixer_does_not_mutate_inputs():
    obstacle = empty_obstacle_command()
    navigation = navigation_command_for_event(NavigationEventType.LEFT)
    mix_obstacle_and_navigation(obstacle, navigation)
    assert obstacle == empty_obstacle_command()
    assert navigation == navigation_command_for_event(NavigationEventType.LEFT)
