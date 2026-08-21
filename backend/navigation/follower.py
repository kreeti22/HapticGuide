"""
follower.py
-----------
Live GPS route following and next maneuver tracking service (Phase 5).

Continuously matches user GPS coordinates against the calculated OSRM route,
tracks current step progression, calculates distance to upcoming maneuvers,
detects off-route deviation, and flags destination arrival.

Isolated inside the navigation package. Does not touch obstacle detection,
ESP32 communication, camera/TCP streaming, or generate haptic pulses.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from navigation.routing import format_step_instruction, map_maneuver_code
from navigation.search import haversine_distance_m
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

logger = logging.getLogger(__name__)

DEFAULT_STEP_TRANSITION_THRESHOLD_M: float = 20.0
DEFAULT_UPCOMING_MANEUVER_THRESHOLD_M: float = 50.0
DEFAULT_ARRIVAL_THRESHOLD_M: float = 20.0
DEFAULT_OFF_ROUTE_THRESHOLD_M: float = 60.0


@dataclass(frozen=True)
class RouteProgress:
    """Snapshot of current route following progress and maneuver state."""

    active: bool
    current_position: Optional[GeoPoint] = None
    current_step_index: int = 0
    total_steps: int = 0
    current_instruction: Optional[NavigationInstruction] = None
    next_instruction: Optional[NavigationInstruction] = None
    next_maneuver: Optional[str] = None
    distance_to_next_m: Optional[float] = None
    remaining_distance_m: Optional[float] = None
    is_maneuver_imminent: bool = False
    is_off_route: bool = False
    is_arrived: bool = False


def point_to_segment_distance_m(
    p_lat: float,
    p_lon: float,
    a_lat: float,
    a_lon: float,
    b_lat: float,
    b_lon: float,
) -> float:
    """
    Calculate minimum distance from point P to line segment AB in meters
    using equirectangular local planar projection.
    """
    mean_lat_rad = math.radians((a_lat + b_lat + p_lat) / 3.0)
    kx = 111320.0 * math.cos(mean_lat_rad)
    ky = 110540.0

    # Local coordinates relative to point A
    px = (p_lon - a_lon) * kx
    py = (p_lat - a_lat) * ky
    bx = (b_lon - a_lon) * kx
    by = (b_lat - a_lat) * ky

    seg_len_sq = bx * bx + by * by
    if seg_len_sq <= 1e-6:
        return math.hypot(px, py)

    # Project point P onto segment AB
    t = max(0.0, min(1.0, (px * bx + py * by) / seg_len_sq))
    proj_x = t * bx
    proj_y = t * by

    return math.hypot(px - proj_x, py - proj_y)


def distance_to_route_geometry_m(
    origin: GeoPoint,
    geometry: Optional[Dict[str, object]],
    steps: Sequence[RouteStep],
) -> float:
    """
    Find shortest distance in meters from point to route polyline or step points.
    """
    min_dist = float("inf")

    # Check GeoJSON geometry coordinates if present
    if isinstance(geometry, dict) and geometry.get("type") == "LineString":
        coords = geometry.get("coordinates")
        if isinstance(coords, list) and len(coords) >= 2:
            for i in range(len(coords) - 1):
                c1 = coords[i]
                c2 = coords[i + 1]
                if isinstance(c1, list) and len(c1) >= 2 and isinstance(c2, list) and len(c2) >= 2:
                    dist = point_to_segment_distance_m(
                        origin.latitude,
                        origin.longitude,
                        c1[1],
                        c1[0],
                        c2[1],
                        c2[0],
                    )
                    if dist < min_dist:
                        min_dist = dist

    # Fallback to checking step maneuver points
    if math.isinf(min_dist):
        for step in steps:
            if step.location is not None:
                d = haversine_distance_m(
                    origin.latitude,
                    origin.longitude,
                    step.location.latitude,
                    step.location.longitude,
                )
                if d < min_dist:
                    min_dist = d

    return min_dist if not math.isinf(min_dist) else 0.0


class RouteFollower:
    """
    Evaluates real-time GPS fixes against active route and updates NavigationState.
    """

    def __init__(
        self,
        step_threshold_m: float = DEFAULT_STEP_TRANSITION_THRESHOLD_M,
        upcoming_threshold_m: float = DEFAULT_UPCOMING_MANEUVER_THRESHOLD_M,
        arrival_threshold_m: float = DEFAULT_ARRIVAL_THRESHOLD_M,
        off_route_threshold_m: float = DEFAULT_OFF_ROUTE_THRESHOLD_M,
    ) -> None:
        self.step_threshold_m = step_threshold_m
        self.upcoming_threshold_m = upcoming_threshold_m
        self.arrival_threshold_m = arrival_threshold_m
        self.off_route_threshold_m = off_route_threshold_m

    def update(
        self,
        state: NavigationState,
        fix: Optional[GpsFix] = None,
    ) -> RouteProgress:
        """
        Evaluate current GPS fix against active route, progress steps,
        update distance to maneuver, detect arrival, and check off-route status.
        """
        route = state.active_route
        if route is None or not route.steps:
            return RouteProgress(active=False)

        # Allow route following when ROUTE_READY, NAVIGATING, or OFF_ROUTE
        if state.status not in (
            NavigationStatus.ROUTE_READY,
            NavigationStatus.NAVIGATING,
            NavigationStatus.OFF_ROUTE,
            NavigationStatus.ARRIVED,
        ):
            return RouteProgress(active=False)

        current_fix = fix or state.current_location
        if current_fix is None:
            return RouteProgress(active=False)

        user_pos = GeoPoint(latitude=current_fix.latitude, longitude=current_fix.longitude)

        # If ROUTE_READY, begin navigation automatically on first GPS fix
        if state.status is NavigationStatus.ROUTE_READY:
            state.begin_navigation()

        dest_point = state.destination or (
            route.steps[-1].location if route.steps[-1].location else None
        )

        # -------------------------------------------------------------------
        # 1. Arrival Check
        # -------------------------------------------------------------------
        dist_to_dest = (
            haversine_distance_m(
                user_pos.latitude,
                user_pos.longitude,
                dest_point.latitude,
                dest_point.longitude,
            )
            if dest_point
            else float("inf")
        )

        if dist_to_dest <= self.arrival_threshold_m:
            if state.status is not NavigationStatus.ARRIVED:
                state.mark_arrived()

            arr_instruction = NavigationInstruction(
                text="You have arrived at your destination",
                maneuver="ARRIVAL",
                distance_m=0.0,
                step_index=len(route.steps) - 1,
            )
            state.current_instruction = arr_instruction
            state.next_instruction = None
            state.distance_to_next_m = 0.0
            state.remaining_distance_m = 0.0
            state.is_maneuver_imminent = False
            state.current_step_index = len(route.steps) - 1

            return RouteProgress(
                active=True,
                current_position=user_pos,
                current_step_index=state.current_step_index,
                total_steps=len(route.steps),
                current_instruction=arr_instruction,
                next_instruction=None,
                next_maneuver="ARRIVAL",
                distance_to_next_m=0.0,
                remaining_distance_m=0.0,
                is_maneuver_imminent=False,
                is_off_route=False,
                is_arrived=True,
            )

        # -------------------------------------------------------------------
        # 2. Off-Route Check
        # -------------------------------------------------------------------
        dist_from_route = distance_to_route_geometry_m(
            user_pos,
            route.geometry,
            route.steps,
        )

        is_off_route = dist_from_route > self.off_route_threshold_m
        if is_off_route:
            if state.status is NavigationStatus.NAVIGATING:
                state.mark_off_route()
        else:
            if state.status is NavigationStatus.OFF_ROUTE:
                state._transition(NavigationStatus.NAVIGATING)
                state.route_status = RouteStatus.ACTIVE

        # -------------------------------------------------------------------
        # 3. Step Progression
        # -------------------------------------------------------------------
        step_idx = state.current_step_index
        steps = route.steps

        # Check if user reached/passed upcoming maneuver points
        while step_idx + 1 < len(steps):
            next_step_loc = steps[step_idx + 1].location
            if next_step_loc is not None:
                dist_to_step_maneuver = haversine_distance_m(
                    user_pos.latitude,
                    user_pos.longitude,
                    next_step_loc.latitude,
                    next_step_loc.longitude,
                )
                if dist_to_step_maneuver <= self.step_threshold_m:
                    step_idx += 1
                else:
                    break
            else:
                break

        state.current_step_index = step_idx
        current_step = steps[step_idx]
        next_step = steps[step_idx + 1] if step_idx + 1 < len(steps) else None

        # -------------------------------------------------------------------
        # 4. Distance to Next Maneuver & Remaining Distance
        # -------------------------------------------------------------------
        target_loc = next_step.location if (next_step and next_step.location) else dest_point

        if target_loc is not None:
            dist_to_next = haversine_distance_m(
                user_pos.latitude,
                user_pos.longitude,
                target_loc.latitude,
                target_loc.longitude,
            )
        else:
            dist_to_next = current_step.distance_m

        # Sum of distances of remaining subsequent steps
        future_steps_dist = sum(s.distance_m for s in steps[step_idx + 2 :]) if step_idx + 2 < len(steps) else 0.0
        remaining_dist = dist_to_next + future_steps_dist

        is_imminent = dist_to_next <= self.upcoming_threshold_m

        current_inst = NavigationInstruction(
            text=current_step.instruction,
            maneuver=map_maneuver_code(current_step.maneuver_type, current_step.maneuver_modifier),
            distance_m=round(dist_to_next, 1),
            step_index=step_idx,
            road_name=current_step.road_name,
        )

        next_inst: Optional[NavigationInstruction] = None
        if next_step is not None:
            next_inst = NavigationInstruction(
                text=next_step.instruction,
                maneuver=map_maneuver_code(next_step.maneuver_type, next_step.maneuver_modifier),
                distance_m=round(next_step.distance_m, 1),
                step_index=step_idx + 1,
                road_name=next_step.road_name,
            )

        next_maneuver_token = next_inst.maneuver if next_inst else current_inst.maneuver

        # Update NavigationState fields
        state.current_instruction = current_inst
        state.next_instruction = next_inst
        state.distance_to_next_m = round(dist_to_next, 1)
        state.remaining_distance_m = round(remaining_dist, 1)
        state.is_maneuver_imminent = is_imminent

        return RouteProgress(
            active=True,
            current_position=user_pos,
            current_step_index=step_idx,
            total_steps=len(steps),
            current_instruction=current_inst,
            next_instruction=next_inst,
            next_maneuver=next_maneuver_token,
            distance_to_next_m=round(dist_to_next, 1),
            remaining_distance_m=round(remaining_dist, 1),
            is_maneuver_imminent=is_imminent,
            is_off_route=is_off_route,
            is_arrived=False,
        )


_DEFAULT_FOLLOWER = RouteFollower()


def update_route_progress(
    state: NavigationState,
    fix: Optional[GpsFix] = None,
    follower: Optional[RouteFollower] = None,
) -> RouteProgress:
    """Convenience function to update route following and emit navigation events."""
    f = follower or _DEFAULT_FOLLOWER
    progress = f.update(state, fix=fix)

    try:
        from navigation.emitter import get_emitter
        emitter = get_emitter(state)
        emitter.evaluate_and_emit(state, progress)
    except Exception as exc:
        logger.debug("Emitter evaluation: %s", exc)

    return progress
