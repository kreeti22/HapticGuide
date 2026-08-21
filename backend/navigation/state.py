"""
Navigation session state (Phase 1).

Holds destination, GPS placeholders, route/instruction fields, and a
status machine. It does not call GPS/OSM/OSRM/Groq, does not play
haptics, and does not write obstacle PWM (globals.latest_command).

Haptic intent is expressed only as NavigationEventType values from the
Phase 0 contract. Playback is a later phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

from navigation.contract import NAVIGATION_EVENT_SPECS, NavigationEventType


class NavigationStatus(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    SEARCHING_DESTINATION = "SEARCHING_DESTINATION"
    DESTINATION_FOUND = "DESTINATION_FOUND"
    CALCULATING_ROUTE = "CALCULATING_ROUTE"
    ROUTE_READY = "ROUTE_READY"
    NAVIGATING = "NAVIGATING"
    ARRIVED = "ARRIVED"
    OFF_ROUTE = "OFF_ROUTE"
    ERROR = "ERROR"


class RouteStatus(str, Enum):
    NONE = "NONE"
    CALCULATING = "CALCULATING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    OFF_ROUTE = "OFF_ROUTE"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class GpsHealth(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    GPS_UNAVAILABLE = "GPS_UNAVAILABLE"
    LOCATION_UNAVAILABLE = "LOCATION_UNAVAILABLE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class GpsFix:
    """One phone GPS sample ingested into navigation state."""

    latitude: float
    longitude: float
    accuracy_m: Optional[float] = None
    received_at_monotonic: Optional[float] = None


@dataclass(frozen=True)
class PlaceCandidate:
    """Overpass/OSM search result candidate."""

    name: str
    location: GeoPoint
    distance_m: Optional[float] = None
    osm_id: Optional[int] = None
    osm_type: Optional[str] = None
    tags: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class RouteStep:
    """One step/maneuver along a calculated route."""

    instruction: str
    maneuver_type: str
    maneuver_modifier: Optional[str] = None
    location: Optional[GeoPoint] = None
    distance_m: float = 0.0
    duration_s: float = 0.0
    road_name: Optional[str] = None


@dataclass(frozen=True)
class NavigationInstruction:
    text: str
    maneuver: Optional[str] = None
    distance_m: Optional[float] = None
    step_index: Optional[int] = None
    road_name: Optional[str] = None


@dataclass(frozen=True)
class RouteSnapshot:
    """Calculated route snapshot."""

    current: Optional[NavigationInstruction] = None
    next: Optional[NavigationInstruction] = None
    distance_to_next_m: Optional[float] = None
    remaining_distance_m: Optional[float] = None
    total_distance_m: Optional[float] = None
    total_duration_s: Optional[float] = None
    steps: Sequence[RouteStep] = field(default_factory=tuple)
    geometry: Optional[Dict[str, object]] = None
    origin: Optional[GeoPoint] = None
    destination: Optional[GeoPoint] = None


_ALLOWED_TRANSITIONS: Dict[NavigationStatus, set] = {
    NavigationStatus.IDLE: {
        NavigationStatus.LISTENING,
        NavigationStatus.SEARCHING_DESTINATION,
        NavigationStatus.CALCULATING_ROUTE,
        NavigationStatus.ERROR,
    },
    NavigationStatus.LISTENING: {
        NavigationStatus.SEARCHING_DESTINATION,
        NavigationStatus.CALCULATING_ROUTE,
        NavigationStatus.IDLE,
        NavigationStatus.ERROR,
    },
    NavigationStatus.SEARCHING_DESTINATION: {
        NavigationStatus.DESTINATION_FOUND,
        NavigationStatus.CALCULATING_ROUTE,
        NavigationStatus.ERROR,
        NavigationStatus.IDLE,
    },
    NavigationStatus.DESTINATION_FOUND: {
        NavigationStatus.CALCULATING_ROUTE,
        NavigationStatus.SEARCHING_DESTINATION,
        NavigationStatus.ERROR,
        NavigationStatus.IDLE,
    },
    NavigationStatus.CALCULATING_ROUTE: {
        NavigationStatus.ROUTE_READY,
        NavigationStatus.SEARCHING_DESTINATION,
        NavigationStatus.ERROR,
        NavigationStatus.IDLE,
    },
    NavigationStatus.ROUTE_READY: {
        NavigationStatus.NAVIGATING,
        NavigationStatus.CALCULATING_ROUTE,
        NavigationStatus.SEARCHING_DESTINATION,
        NavigationStatus.ERROR,
        NavigationStatus.IDLE,
    },
    NavigationStatus.NAVIGATING: {
        NavigationStatus.ARRIVED,
        NavigationStatus.OFF_ROUTE,
        NavigationStatus.CALCULATING_ROUTE,
        NavigationStatus.SEARCHING_DESTINATION,
        NavigationStatus.ERROR,
        NavigationStatus.IDLE,
    },
    NavigationStatus.OFF_ROUTE: {
        NavigationStatus.CALCULATING_ROUTE,
        NavigationStatus.NAVIGATING,
        NavigationStatus.SEARCHING_DESTINATION,
        NavigationStatus.ERROR,
        NavigationStatus.IDLE,
    },
    NavigationStatus.ARRIVED: {
        NavigationStatus.SEARCHING_DESTINATION,
        NavigationStatus.CALCULATING_ROUTE,
        NavigationStatus.IDLE,
        NavigationStatus.ERROR,
    },
    NavigationStatus.ERROR: {
        NavigationStatus.SEARCHING_DESTINATION,
        NavigationStatus.CALCULATING_ROUTE,
        NavigationStatus.LISTENING,
        NavigationStatus.IDLE,
    },
}

_MANEUVER_TO_EVENT = {
    "LEFT": NavigationEventType.LEFT,
    "RIGHT": NavigationEventType.RIGHT,
    "FRONT": NavigationEventType.FRONT,
    "STRAIGHT": NavigationEventType.FRONT,
}


def haptic_event_for_maneuver(maneuver: str) -> NavigationEventType:
    """Map a turn instruction to a Phase 0 event. Does not play pulses."""
    key = maneuver.strip().upper()
    if key not in _MANEUVER_TO_EVENT:
        raise ValueError(f"Unsupported navigation maneuver: {maneuver!r}")
    return _MANEUVER_TO_EVENT[key]


@dataclass
class NavigationState:
    """
    In-memory navigation session.

    Future GPS / search / routing services fill these fields; they must
    not call decision_engine or globals.latest_command.
    """

    status: NavigationStatus = NavigationStatus.IDLE
    route_status: RouteStatus = RouteStatus.NONE
    destination_query: Optional[str] = None
    destination_name: Optional[str] = None
    destination: Optional[GeoPoint] = None
    destination_distance_m: Optional[float] = None
    destination_candidate: Optional[PlaceCandidate] = None
    current_location: Optional[GpsFix] = None
    current_instruction: Optional[NavigationInstruction] = None
    next_instruction: Optional[NavigationInstruction] = None
    distance_to_next_m: Optional[float] = None
    remaining_distance_m: Optional[float] = None
    total_route_distance_m: Optional[float] = None
    total_route_duration_s: Optional[float] = None
    active_route: Optional[RouteSnapshot] = None
    current_step_index: int = 0
    is_maneuver_imminent: bool = False
    error_message: Optional[str] = None
    pending_haptic_event: Optional[NavigationEventType] = None
    gps_health: GpsHealth = GpsHealth.NONE
    gps_detail: Optional[str] = None
    gps_received_at: Optional[float] = None
    _history: list = field(default_factory=list, repr=False)

    def snapshot(self) -> Dict[str, object]:
        dest = self.destination
        loc = self.current_location
        return {
            "status": self.status.value,
            "route_status": self.route_status.value,
            "destination_query": self.destination_query,
            "destination_name": self.destination_name,
            "destination_latitude": None if dest is None else dest.latitude,
            "destination_longitude": None if dest is None else dest.longitude,
            "destination_distance_m": self.destination_distance_m,
            "current_latitude": None if loc is None else loc.latitude,
            "current_longitude": None if loc is None else loc.longitude,
            "current_instruction": None if self.current_instruction is None else self.current_instruction.text,
            "next_instruction": None if self.next_instruction is None else self.next_instruction.text,
            "current_step_index": self.current_step_index,
            "distance_to_next_m": self.distance_to_next_m,
            "remaining_distance_m": self.remaining_distance_m,
            "total_route_distance_m": self.total_route_distance_m,
            "total_route_duration_s": self.total_route_duration_s,
            "route_steps_count": len(self.active_route.steps) if (self.active_route and self.active_route.steps) else 0,
            "is_off_route": (self.status == NavigationStatus.OFF_ROUTE),
            "is_arrived": (self.status == NavigationStatus.ARRIVED),
            "is_maneuver_imminent": self.is_maneuver_imminent,
            "error_message": self.error_message,
            "pending_haptic_event": (
                None if self.pending_haptic_event is None else self.pending_haptic_event.value
            ),
            "gps_health": self.gps_health.value,
            "gps_detail": self.gps_detail,
            "gps_age_ms": None,
            "gps_stale": False,
            "gps_accuracy_m": None if loc is None else loc.accuracy_m,
        }

    def _transition(self, nxt: NavigationStatus) -> None:
        allowed = _ALLOWED_TRANSITIONS[self.status]
        if nxt not in allowed:
            raise ValueError(f"Invalid navigation transition: {self.status.value} → {nxt.value}")
        self._history.append(self.status)
        self.status = nxt
        if nxt != NavigationStatus.ERROR:
            self.error_message = None

    def begin_input(self) -> None:
        self._transition(NavigationStatus.LISTENING)

    def set_destination_query(self, query: str) -> None:
        text = query.strip()
        if not text:
            raise ValueError("Destination query must be non-empty.")
        self.destination_query = text

    def begin_search(self) -> None:
        self._transition(NavigationStatus.SEARCHING_DESTINATION)
        self.route_status = RouteStatus.NONE

    def set_destination(self, candidate: PlaceCandidate) -> None:
        if self.status is not NavigationStatus.SEARCHING_DESTINATION:
            raise ValueError("Destination can be stored only while SEARCHING_DESTINATION.")
        self.destination_name = candidate.name
        self.destination = candidate.location
        self.destination_distance_m = candidate.distance_m
        self.destination_candidate = candidate
        self._transition(NavigationStatus.DESTINATION_FOUND)

    def begin_route_calculation(self) -> None:
        self._transition(NavigationStatus.CALCULATING_ROUTE)
        self.route_status = RouteStatus.CALCULATING

    def set_route(self, route: RouteSnapshot) -> None:
        if self.status is not NavigationStatus.CALCULATING_ROUTE:
            raise ValueError("Route can be stored only while CALCULATING_ROUTE.")
        self.current_instruction = route.current
        self.next_instruction = route.next
        self.distance_to_next_m = route.distance_to_next_m
        self.remaining_distance_m = route.remaining_distance_m
        self.total_route_distance_m = route.total_distance_m
        self.total_route_duration_s = route.total_duration_s
        self.active_route = route
        self.current_step_index = 0
        self.is_maneuver_imminent = False
        self.route_status = RouteStatus.READY
        self._transition(NavigationStatus.ROUTE_READY)

    def begin_navigation(self) -> None:
        self._transition(NavigationStatus.NAVIGATING)
        self.route_status = RouteStatus.ACTIVE
        self.pending_haptic_event = NavigationEventType.START

    def set_current_location(self, fix: GpsFix) -> None:
        self.current_location = fix
        self.gps_health = GpsHealth.ACTIVE
        self.gps_detail = None
        self.gps_received_at = fix.received_at_monotonic

    def set_gps_fault(self, health: GpsHealth, detail: str) -> None:
        if health is GpsHealth.ACTIVE or health is GpsHealth.NONE:
            raise ValueError("GPS fault health must be a failure or stale state.")
        self.gps_health = health
        self.gps_detail = detail.strip() or health.value

    def update_guidance(
        self,
        current: Optional[NavigationInstruction] = None,
        next_instruction: Optional[NavigationInstruction] = None,
        distance_to_next_m: Optional[float] = None,
        remaining_distance_m: Optional[float] = None,
    ) -> None:
        if self.status not in (NavigationStatus.NAVIGATING, NavigationStatus.ROUTE_READY):
            raise ValueError("Guidance can be updated only while ROUTE_READY or NAVIGATING.")
        if current is not None:
            self.current_instruction = current
        if next_instruction is not None:
            self.next_instruction = next_instruction
        if distance_to_next_m is not None:
            self.distance_to_next_m = distance_to_next_m
        if remaining_distance_m is not None:
            self.remaining_distance_m = remaining_distance_m

    def mark_off_route(self) -> None:
        self._transition(NavigationStatus.OFF_ROUTE)
        self.route_status = RouteStatus.OFF_ROUTE

    def mark_arrived(self) -> None:
        self._transition(NavigationStatus.ARRIVED)
        self.route_status = RouteStatus.COMPLETE
        self.pending_haptic_event = NavigationEventType.ARRIVAL

    def fail(self, message: str) -> None:
        text = message.strip()
        if not text:
            raise ValueError("Error message must be non-empty.")
        self._transition(NavigationStatus.ERROR)
        self.error_message = text
        self.route_status = RouteStatus.FAILED
        self.pending_haptic_event = None

    def reset(self) -> None:
        if self.status != NavigationStatus.IDLE:
            self._transition(NavigationStatus.IDLE)
        self.route_status = RouteStatus.NONE
        self.destination_query = None
        self.destination_name = None
        self.destination = None
        self.destination_distance_m = None
        self.destination_candidate = None
        self.current_location = None
        self.current_instruction = None
        self.next_instruction = None
        self.distance_to_next_m = None
        self.remaining_distance_m = None
        self.total_route_distance_m = None
        self.total_route_duration_s = None
        self.active_route = None
        self.current_step_index = 0
        self.is_maneuver_imminent = False
        self.error_message = None
        self.pending_haptic_event = None
        self.gps_health = GpsHealth.NONE
        self.gps_detail = None
        self.gps_received_at = None

    def haptic_event_for_current_instruction(self) -> Optional[NavigationEventType]:
        if self.current_instruction is None or self.current_instruction.maneuver is None:
            return None
        return haptic_event_for_maneuver(self.current_instruction.maneuver)


def event_targets(event_type: NavigationEventType):
    return NAVIGATION_EVENT_SPECS[event_type].targets
