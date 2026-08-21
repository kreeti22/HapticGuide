"""
Phone GPS ingest for navigation state.

Validates coordinates, records freshness, and maps permission/hardware
faults. Does not call OSM, OSRM, Groq, or the obstacle pipeline.
"""

from __future__ import annotations

import math
import time
from typing import Dict, Optional

from navigation.interfaces import LocationSource
from navigation.state import GpsFix, GpsHealth, NavigationState, NavigationStatus

STALE_AFTER_S = 8.0


class GpsIngestError(ValueError):
    def __init__(self, health: GpsHealth, message: str) -> None:
        super().__init__(message)
        self.health = health
        self.message = message


def validate_coordinates(latitude: object, longitude: object) -> tuple[float, float]:
    if latitude is None or longitude is None:
        raise GpsIngestError(
            GpsHealth.LOCATION_UNAVAILABLE,
            "Latitude and longitude are required.",
        )
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise GpsIngestError(
            GpsHealth.LOCATION_UNAVAILABLE,
            "Latitude and longitude must be numbers, not booleans.",
        )
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise GpsIngestError(
            GpsHealth.LOCATION_UNAVAILABLE,
            "Latitude and longitude must be numbers.",
        ) from exc
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise GpsIngestError(
            GpsHealth.LOCATION_UNAVAILABLE,
            "Latitude and longitude must be finite.",
        )
    if not -90.0 <= lat <= 90.0:
        raise GpsIngestError(
            GpsHealth.LOCATION_UNAVAILABLE,
            "Latitude must be between -90 and 90.",
        )
    if not -180.0 <= lon <= 180.0:
        raise GpsIngestError(
            GpsHealth.LOCATION_UNAVAILABLE,
            "Longitude must be between -180 and 180.",
        )
    return lat, lon


def apply_gps_fix(
    state: NavigationState,
    latitude: object,
    longitude: object,
    accuracy_m: Optional[object] = None,
    now: Optional[float] = None,
) -> Dict[str, object]:
    lat, lon = validate_coordinates(latitude, longitude)
    received = time.monotonic() if now is None else now
    accuracy: Optional[float] = None
    if accuracy_m is not None:
        if isinstance(accuracy_m, bool):
            accuracy = None
        else:
            try:
                accuracy = float(accuracy_m)
            except (TypeError, ValueError):
                accuracy = None
            if accuracy is not None and (not math.isfinite(accuracy) or accuracy < 0):
                accuracy = None
    fix = GpsFix(
        latitude=lat,
        longitude=lon,
        accuracy_m=accuracy,
        received_at_monotonic=received,
    )
    state.set_current_location(fix)

    if state.active_route is not None and state.status in (
        NavigationStatus.ROUTE_READY,
        NavigationStatus.NAVIGATING,
        NavigationStatus.OFF_ROUTE,
    ):
        from navigation.follower import update_route_progress
        update_route_progress(state, fix=fix)

    return gps_status_payload(state, now=received)


def apply_gps_fault(
    state: NavigationState,
    health: GpsHealth,
    detail: str,
) -> Dict[str, object]:
    if health is GpsHealth.ACTIVE:
        raise ValueError("ACTIVE is not a GPS fault.")
    state.set_gps_fault(health, detail)
    return gps_status_payload(state)


def gps_status_payload(
    state: NavigationState,
    now: Optional[float] = None,
    stale_after_s: float = STALE_AFTER_S,
) -> Dict[str, object]:
    payload = state.snapshot()
    clock = time.monotonic() if now is None else now
    age_ms: Optional[float] = None
    stale = False
    health = state.gps_health
    if state.gps_received_at is not None:
        age_ms = round((clock - state.gps_received_at) * 1000.0, 1)
        if age_ms > stale_after_s * 1000.0 and health is GpsHealth.ACTIVE:
            stale = True
            health = GpsHealth.STALE
    payload["gps_health"] = health.value
    payload["gps_stale"] = stale
    payload["gps_age_ms"] = age_ms
    loc = state.current_location
    payload["gps_accuracy_m"] = None if loc is None else loc.accuracy_m
    return payload


class SessionLocationSource:
    """LocationSource backed by the in-memory navigation session."""

    def __init__(self, state: NavigationState) -> None:
        self._state = state

    def current_fix(self) -> Optional[GpsFix]:
        return self._state.current_location


def health_from_name(name: object) -> GpsHealth:
    if not isinstance(name, str) or not name.strip():
        raise GpsIngestError(GpsHealth.ERROR, "GPS fault type is required.")
    key = name.strip().upper()
    try:
        health = GpsHealth[key] if key in GpsHealth.__members__ else GpsHealth(key)
    except ValueError as exc:
        raise GpsIngestError(GpsHealth.ERROR, f"Unknown GPS fault: {name!r}") from exc
    if health in (GpsHealth.ACTIVE, GpsHealth.NONE):
        raise GpsIngestError(GpsHealth.ERROR, f"{health.value} is not a fault.")
    return health
