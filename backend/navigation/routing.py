"""
routing.py
----------
OSRM route calculation service (Phase 4).

Takes origin and destination coordinates, queries the public OSRM routing API,
parses the route geometry, total distance, duration, legs, steps, and maneuvers,
and returns a structured RouteSnapshot to update NavigationState.

Isolated inside the navigation package. Does not touch obstacle detection,
ESP32 communication, camera/TCP streaming, or haptic playback.
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from navigation.interfaces import RoutingService
from navigation.state import (
    GeoPoint,
    NavigationInstruction,
    NavigationState,
    NavigationStatus,
    RouteSnapshot,
    RouteStep,
)

logger = logging.getLogger(__name__)

DEFAULT_OSRM_URL: str = "https://router.project-osrm.org"
DEFAULT_PROFILE: str = "driving"
DEFAULT_TIMEOUT_S: float = 10.0
USER_AGENT: str = "HapticGuide/1.0 (Wearable Haptic Navigation)"


class RouteCalculationError(Exception):
    """Raised when OSRM routing fails due to network, service, or parsing errors."""


def build_osrm_url(
    origin: GeoPoint,
    destination: GeoPoint,
    base_url: str = DEFAULT_OSRM_URL,
    profile: str = DEFAULT_PROFILE,
) -> str:
    """
    Build OSRM route request URL.
    CRITICAL: Coordinates must be ordered as (longitude, latitude).
    """
    clean_base = base_url.rstrip("/")
    # OSRM coordinate order: {lon},{lat};{lon},{lat}
    coords = (
        f"{origin.longitude:.6f},{origin.latitude:.6f};"
        f"{destination.longitude:.6f},{destination.latitude:.6f}"
    )
    params = urllib.parse.urlencode(
        {
            "steps": "true",
            "overview": "full",
            "geometries": "geojson",
        }
    )
    return f"{clean_base}/route/v1/{profile}/{coords}?{params}"


def map_maneuver_code(maneuver_type: str, maneuver_modifier: Optional[str] = None) -> Optional[str]:
    """
    Map OSRM maneuver type and modifier to a high-level turn code (e.g. LEFT, RIGHT, STRAIGHT, ARRIVAL).
    """
    m_type = (maneuver_type or "").strip().lower()
    m_mod = (maneuver_modifier or "").strip().lower()

    if m_type == "arrive":
        return "ARRIVAL"

    if "left" in m_mod:
        return "LEFT"
    if "right" in m_mod:
        return "RIGHT"
    if "straight" in m_mod or m_type in ("depart", "continue", "new name"):
        return "STRAIGHT"

    return "STRAIGHT"


def format_step_instruction(
    maneuver_type: str,
    maneuver_modifier: Optional[str],
    road_name: str,
) -> str:
    """Generate human-readable turn-by-turn instruction text from step maneuver."""
    m_type = (maneuver_type or "").strip().lower()
    m_mod = (maneuver_modifier or "").strip().lower()
    road = road_name.strip() if road_name else ""

    if m_type == "arrive":
        return "You have arrived at your destination"

    if m_type == "depart":
        if road:
            return f"Head {m_mod or 'straight'} on {road}"
        return f"Head {m_mod or 'straight'}"

    if m_type == "turn":
        if m_mod:
            if road:
                return f"Turn {m_mod} onto {road}"
            return f"Turn {m_mod}"
        if road:
            return f"Turn onto {road}"
        return "Turn"

    if m_type == "new name":
        if road:
            return f"Continue onto {road}"
        return "Continue"

    if m_type == "continue":
        if road:
            return f"Continue on {road}"
        return "Continue straight"

    if m_type in ("roundabout", "rotary"):
        if road:
            return f"Enter roundabout and take exit onto {road}"
        return "Enter roundabout"

    if m_type == "fork":
        if m_mod:
            if road:
                return f"Take the {m_mod} fork onto {road}"
            return f"Take the {m_mod} fork"
        return "Take the fork"

    if m_type == "merge":
        if road:
            return f"Merge onto {road}"
        return "Merge"

    # Default fallback
    if road:
        if m_mod:
            return f"Proceed {m_mod} on {road}"
        return f"Proceed on {road}"
    return "Continue"


def parse_osrm_response(
    data: Dict[str, object],
    origin: GeoPoint,
    destination: GeoPoint,
) -> RouteSnapshot:
    """
    Parse OSRM JSON response into a structured RouteSnapshot.
    """
    code = data.get("code")
    if code != "Ok":
        msg = data.get("message") or f"Error code: {code}"
        raise RouteCalculationError(f"OSRM route calculation failed ({code}): {msg}")

    routes = data.get("routes")
    if not isinstance(routes, list) or not routes:
        raise RouteCalculationError("OSRM response contains no routes.")

    primary_route = routes[0]
    if not isinstance(primary_route, dict):
        raise RouteCalculationError("Malformed route structure in OSRM response.")

    total_distance_m = float(primary_route.get("distance", 0.0))
    total_duration_s = float(primary_route.get("duration", 0.0))
    geometry = primary_route.get("geometry") if isinstance(primary_route.get("geometry"), dict) else None

    legs = primary_route.get("legs")
    if not isinstance(legs, list) or not legs:
        raise RouteCalculationError("OSRM route contains no legs.")

    route_steps: List[RouteStep] = []
    nav_instructions: List[NavigationInstruction] = []

    step_idx = 0
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        raw_steps = leg.get("steps")
        if not isinstance(raw_steps, list):
            continue

        for step in raw_steps:
            if not isinstance(step, dict):
                continue

            dist = float(step.get("distance", 0.0))
            dur = float(step.get("duration", 0.0))
            road = str(step.get("name", ""))

            maneuver = step.get("maneuver") if isinstance(step.get("maneuver"), dict) else {}
            m_type = str(maneuver.get("type", "turn"))
            m_mod = str(maneuver.get("modifier", "")) if maneuver.get("modifier") else None

            # OSRM location is [lon, lat]
            loc_coords = maneuver.get("location")
            maneuver_loc: Optional[GeoPoint] = None
            if isinstance(loc_coords, list) and len(loc_coords) >= 2:
                try:
                    maneuver_loc = GeoPoint(
                        latitude=float(loc_coords[1]),
                        longitude=float(loc_coords[0]),
                    )
                except (TypeError, ValueError):
                    pass

            instruction_text = format_step_instruction(m_type, m_mod, road)
            maneuver_code = map_maneuver_code(m_type, m_mod)

            route_step = RouteStep(
                instruction=instruction_text,
                maneuver_type=m_type,
                maneuver_modifier=m_mod,
                location=maneuver_loc,
                distance_m=round(dist, 1),
                duration_s=round(dur, 1),
                road_name=road if road else None,
            )
            route_steps.append(route_step)

            nav_inst = NavigationInstruction(
                text=instruction_text,
                maneuver=maneuver_code,
                distance_m=round(dist, 1),
                step_index=step_idx,
                road_name=road if road else None,
            )
            nav_instructions.append(nav_inst)
            step_idx += 1

    current_instruction = nav_instructions[0] if nav_instructions else None
    next_instruction = nav_instructions[1] if len(nav_instructions) > 1 else None
    dist_to_next = current_instruction.distance_m if current_instruction else None

    return RouteSnapshot(
        current=current_instruction,
        next=next_instruction,
        distance_to_next_m=dist_to_next,
        remaining_distance_m=round(total_distance_m, 1),
        total_distance_m=round(total_distance_m, 1),
        total_duration_s=round(total_duration_s, 1),
        steps=tuple(route_steps),
        geometry=geometry,
        origin=origin,
        destination=destination,
    )


class OsrmRoutingService(RoutingService):
    """
    RoutingService backed by public OSRM HTTP API.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        profile: str = DEFAULT_PROFILE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        user_agent: str = USER_AGENT,
        http_requester: Optional[Callable[[str, float], str]] = None,
    ) -> None:
        self.base_url = base_url or os.environ.get("OSRM_URL", DEFAULT_OSRM_URL)
        self.profile = profile
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        self.is_custom_requester = http_requester is not None
        self._http_requester = http_requester or self._default_http_get

    def _default_http_get(self, url: str, timeout_s: float) -> str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            return response.read().decode("utf-8", errors="replace")

    def calculate_route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
    ) -> Optional[RouteSnapshot]:
        """
        Calculate route between origin and destination using OSRM.
        """
        if not isinstance(origin, GeoPoint):
            raise ValueError("Origin must be a GeoPoint instance.")
        if not isinstance(destination, GeoPoint):
            raise ValueError("Destination must be a GeoPoint instance.")
        if not (-90.0 <= origin.latitude <= 90.0 and -180.0 <= origin.longitude <= 180.0):
            raise ValueError(f"Origin coordinates out of range: {origin}")
        if not (-90.0 <= destination.latitude <= 90.0 and -180.0 <= destination.longitude <= 180.0):
            raise ValueError(f"Destination coordinates out of range: {destination}")

        base_urls = [self.base_url]
        if not self.is_custom_requester and self.base_url == DEFAULT_OSRM_URL:
            base_urls.append("https://routing.openstreetmap.de/routed-car")

        last_error = None
        raw_response = None
        for b_url in base_urls:
            url = build_osrm_url(origin, destination, base_url=b_url, profile=self.profile)
            try:
                raw_response = self._http_requester(url, self.timeout_s)
                if raw_response:
                    break
            except urllib.error.HTTPError as exc:
                logger.warning("OSRM HTTP error %d at %s: %s", exc.code, b_url, exc.reason)
                last_error = RouteCalculationError(f"OSRM service error (HTTP {exc.code})")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                logger.warning("OSRM connection failure at %s: %s", b_url, exc)
                last_error = RouteCalculationError(f"OSRM network failure: {exc}")
            except Exception as exc:
                logger.warning("OSRM request error at %s: %s", b_url, exc)
                last_error = RouteCalculationError(f"OSRM request failed: {exc}")

        if raw_response is None:
            if last_error:
                raise last_error
            raise RouteCalculationError("OSRM network failure: request timed out.")

        try:
            parsed_json = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Malformed OSRM response JSON: %s", exc)
            raise RouteCalculationError("Malformed response from OSRM service.") from exc

        if not isinstance(parsed_json, dict):
            raise RouteCalculationError("Unexpected response structure from OSRM service.")

        return parse_osrm_response(parsed_json, origin, destination)


def calculate_route_and_update_state(
    state: NavigationState,
    origin: Optional[GeoPoint] = None,
    destination: Optional[GeoPoint] = None,
    service: Optional[RoutingService] = None,
) -> Optional[RouteSnapshot]:
    """
    Orchestrate route calculation and update NavigationState.

    Transitions state from DESTINATION_FOUND (or active/idle) to CALCULATING_ROUTE,
    calls OSRM routing service, and transitions to ROUTE_READY on success or ERROR on failure.
    """
    if origin is None:
        if state.current_location is None:
            state.fail("Current GPS location unavailable for route calculation.")
            return None
        origin = GeoPoint(
            latitude=state.current_location.latitude,
            longitude=state.current_location.longitude,
        )

    if destination is None:
        if state.destination is None:
            state.fail("Destination coordinates unavailable for route calculation.")
            return None
        destination = state.destination

    state.begin_route_calculation()

    routing_svc = service or OsrmRoutingService()

    try:
        route = routing_svc.calculate_route(origin, destination)
    except Exception as exc:
        state.fail(f"Route calculation failed: {exc}")
        return None

    if route is None:
        state.fail("No route found between coordinates.")
        return None

    state.set_route(route)
    return route
