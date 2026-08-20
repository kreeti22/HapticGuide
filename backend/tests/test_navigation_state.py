"""
test_navigation_state.py
------------------------
Phase 1: in-memory navigation session state.

Does not call GPS, Groq, OSM, OSRM, or play haptics.
Does not write obstacle PWM.
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import globals
from navigation.contract import NavigationEventType, NavigationTarget
from navigation.interfaces import (
    DestinationSearchService,
    LocationSource,
    RoutingService,
    SpeechToTextService,
)
from navigation.state import (
    GeoPoint,
    GpsFix,
    NavigationInstruction,
    NavigationState,
    NavigationStatus,
    PlaceCandidate,
    RouteSnapshot,
    RouteStatus,
    haptic_event_for_maneuver,
)


def _sample_place() -> PlaceCandidate:
    return PlaceCandidate(
        name="Nearest KFC",
        location=GeoPoint(latitude=28.6139, longitude=77.2090),
    )


def _sample_route() -> RouteSnapshot:
    return RouteSnapshot(
        current=NavigationInstruction("Continue straight", maneuver="STRAIGHT", distance_m=40.0),
        next=NavigationInstruction("Turn right", maneuver="RIGHT", distance_m=38.0),
        distance_to_next_m=38.0,
        remaining_distance_m=420.0,
    )


def test_initial_state_is_idle():
    state = NavigationState()
    assert state.status is NavigationStatus.IDLE
    assert state.route_status is RouteStatus.NONE
    assert state.destination_query is None
    assert state.destination is None
    assert state.current_location is None
    assert state.pending_haptic_event is None
    snap = state.snapshot()
    assert snap["status"] == "IDLE"
    assert snap["error_message"] is None


def test_destination_query_can_be_stored():
    state = NavigationState()
    state.set_destination_query("take me to nearest KFC")
    assert state.destination_query == "take me to nearest KFC"
    assert state.status is NavigationStatus.IDLE


def test_destination_coordinates_can_be_stored():
    state = NavigationState()
    state.begin_search()
    state.set_destination(_sample_place())
    assert state.status is NavigationStatus.DESTINATION_FOUND
    assert state.destination_name == "Nearest KFC"
    assert state.destination is not None
    assert state.destination.latitude == 28.6139
    assert state.destination.longitude == 77.2090
    snap = state.snapshot()
    assert snap["destination_latitude"] == 28.6139
    assert snap["destination_longitude"] == 77.2090


def test_current_gps_coordinates_can_be_stored():
    state = NavigationState()
    state.set_current_location(GpsFix(latitude=28.61, longitude=77.20, accuracy_m=5.0))
    assert state.current_location is not None
    assert state.current_location.latitude == 28.61
    assert state.current_location.longitude == 77.20
    snap = state.snapshot()
    assert snap["current_latitude"] == 28.61
    assert snap["current_longitude"] == 77.20
    assert state.status is NavigationStatus.IDLE


def test_state_can_transition_through_valid_navigation_stages():
    state = NavigationState()
    state.begin_input()
    assert state.status is NavigationStatus.LISTENING
    state.set_destination_query("nearest KFC")
    state.begin_search()
    assert state.status is NavigationStatus.SEARCHING_DESTINATION
    state.set_destination(_sample_place())
    assert state.status is NavigationStatus.DESTINATION_FOUND
    state.begin_route_calculation()
    assert state.status is NavigationStatus.CALCULATING_ROUTE
    assert state.route_status is RouteStatus.CALCULATING
    state.set_route(_sample_route())
    assert state.status is NavigationStatus.ROUTE_READY
    state.begin_navigation()
    assert state.status is NavigationStatus.NAVIGATING
    assert state.pending_haptic_event is NavigationEventType.START
    state.mark_off_route()
    assert state.status is NavigationStatus.OFF_ROUTE
    state.begin_route_calculation()
    state.set_route(_sample_route())
    state.begin_navigation()
    state.mark_arrived()
    assert state.status is NavigationStatus.ARRIVED


def test_route_ready_stores_instruction_information():
    state = NavigationState()
    state.begin_search()
    state.set_destination(_sample_place())
    state.begin_route_calculation()
    state.set_route(_sample_route())
    assert state.status is NavigationStatus.ROUTE_READY
    assert state.route_status is RouteStatus.READY
    assert state.current_instruction is not None
    assert state.current_instruction.text == "Continue straight"
    assert state.next_instruction is not None
    assert state.next_instruction.text == "Turn right"
    assert state.distance_to_next_m == 38.0
    assert state.remaining_distance_m == 420.0
    snap = state.snapshot()
    assert snap["current_instruction"] == "Continue straight"
    assert snap["next_instruction"] == "Turn right"
    assert snap["distance_to_next_m"] == 38.0
    assert snap["remaining_distance_m"] == 420.0


def test_navigation_state_can_represent_an_error():
    state = NavigationState()
    state.begin_search()
    state.fail("No matching destination")
    assert state.status is NavigationStatus.ERROR
    assert state.error_message == "No matching destination"
    assert state.route_status is RouteStatus.FAILED
    assert state.snapshot()["error_message"] == "No matching destination"


def test_invalid_transition_is_rejected():
    state = NavigationState()
    try:
        state.begin_navigation()
    except ValueError as exc:
        assert "Invalid navigation transition" in str(exc)
    else:
        raise AssertionError("Expected invalid IDLE → NAVIGATING to fail.")
    assert state.status is NavigationStatus.IDLE


def test_navigation_state_does_not_modify_obstacle_state():
    with globals.command_lock:
        original = dict(globals.latest_command)
        globals.latest_command.update({"left": 0, "front": 180, "right": 0, "back": 0})
        obstacle_before = dict(globals.latest_command)

    try:
        state = NavigationState()
        state.set_destination_query("nearest KFC")
        state.begin_search()
        state.set_destination(_sample_place())
        state.begin_route_calculation()
        state.set_route(_sample_route())
        state.begin_navigation()
        state.fail("simulated")

        with globals.command_lock:
            obstacle_after = dict(globals.latest_command)
    finally:
        with globals.command_lock:
            globals.latest_command.update(original)

    assert obstacle_after == obstacle_before
    assert obstacle_after["front"] == 180


def test_navigation_event_targets_remain_correct():
    assert haptic_event_for_maneuver("LEFT") is NavigationEventType.LEFT
    assert haptic_event_for_maneuver("RIGHT") is NavigationEventType.RIGHT
    assert haptic_event_for_maneuver("FRONT") is NavigationEventType.FRONT
    assert haptic_event_for_maneuver("STRAIGHT") is NavigationEventType.FRONT

    from navigation.contract import NAVIGATION_EVENT_SPECS

    assert NAVIGATION_EVENT_SPECS[NavigationEventType.LEFT].targets == (
        NavigationTarget.BELT_LEFT,
    )
    assert NAVIGATION_EVENT_SPECS[NavigationEventType.RIGHT].targets == (
        NavigationTarget.BELT_RIGHT,
    )
    assert NAVIGATION_EVENT_SPECS[NavigationEventType.FRONT].targets == (
        NavigationTarget.PHONE_FRONT,
    )

    state = NavigationState()
    state.begin_search()
    state.set_destination(_sample_place())
    state.begin_route_calculation()
    state.set_route(_sample_route())
    assert state.haptic_event_for_current_instruction() is NavigationEventType.FRONT


def test_future_service_protocols_are_structural_only():
    assert LocationSource.__name__ == "LocationSource"
    assert DestinationSearchService.__name__ == "DestinationSearchService"
    assert RoutingService.__name__ == "RoutingService"
    assert SpeechToTextService.__name__ == "SpeechToTextService"
