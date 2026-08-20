"""
Navigation haptic contract (Phase 0).

This module is a specification for future navigation code. It is not
connected to FastAPI, the AI worker, decision_engine, or ESP32 polling.

Two independent haptic sources
------------------------------
1. Obstacle system — existing PWM dict {left, front, right, back}.
   Unchanged. Authoritative on every ESP32 belt axis it occupies.
2. Navigation system — additive events targeting belt-left, belt-right,
   and phone-front only. Must never write ESP32 front/back.

NAVIGATION_FRONT / STRAIGHT uses the smartphone vibrator, not the
physical ESP32 front motor (GPIO 13). That motor remains obstacle-only.

Pulse timing values are placeholders for a later sequencer. This module
does not play pulses.

The mix function is the mixer *contract*, not production wiring:
obstacle + navigation → final belt PWM + phone PWM, with obstacle priority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Mapping, Sequence, Tuple


# ---------------------------------------------------------------------------
# Belt vs phone outputs
# ---------------------------------------------------------------------------

BELT_AXES: Tuple[str, ...] = ("left", "front", "right", "back")

# Navigation may drive these keys. ESP32 "front" / "back" are excluded.
NAVIGATION_OUTPUT_KEYS: Tuple[str, ...] = ("left", "right", "phone")

OBSTACLE_COMMAND_KEYS: Tuple[str, ...] = BELT_AXES


class NavigationEventType(str, Enum):
    START = "NAVIGATION_START"
    LEFT = "NAVIGATION_LEFT"
    RIGHT = "NAVIGATION_RIGHT"
    FRONT = "NAVIGATION_FRONT"
    ARRIVAL = "NAVIGATION_ARRIVAL"


class NavigationTarget(str, Enum):
    """Physical (or phone) output a navigation event may drive."""

    BELT_LEFT = "belt-left"
    BELT_RIGHT = "belt-right"
    PHONE_FRONT = "phone-front"


@dataclass(frozen=True)
class NavigationEventSpec:
    """
    Contract for one navigation haptic event.

    pulse_on_ms / pulse_off_ms are timing placeholders. Phase 0 does not
    generate PWM over time.
    """

    event_type: NavigationEventType
    targets: Tuple[NavigationTarget, ...]
    pulse_count: int
    pulse_on_ms: int
    pulse_off_ms: int
    implemented: bool = True


# Placeholder timings — not used for hardware in this phase.
_PULSE_ON_MS = 80
_PULSE_OFF_MS = 80
_START_ON_MS = 80
_START_OFF_MS = 80

NAVIGATION_EVENT_SPECS: Dict[NavigationEventType, NavigationEventSpec] = {
    NavigationEventType.START: NavigationEventSpec(
        event_type=NavigationEventType.START,
        targets=(
            NavigationTarget.BELT_LEFT,
            NavigationTarget.BELT_RIGHT,
            NavigationTarget.PHONE_FRONT,
        ),
        pulse_count=3,
        pulse_on_ms=_START_ON_MS,
        pulse_off_ms=_START_OFF_MS,
    ),
    NavigationEventType.LEFT: NavigationEventSpec(
        event_type=NavigationEventType.LEFT,
        targets=(NavigationTarget.BELT_LEFT,),
        pulse_count=2,
        pulse_on_ms=_PULSE_ON_MS,
        pulse_off_ms=_PULSE_OFF_MS,
    ),
    NavigationEventType.RIGHT: NavigationEventSpec(
        event_type=NavigationEventType.RIGHT,
        targets=(NavigationTarget.BELT_RIGHT,),
        pulse_count=2,
        pulse_on_ms=_PULSE_ON_MS,
        pulse_off_ms=_PULSE_OFF_MS,
    ),
    NavigationEventType.FRONT: NavigationEventSpec(
        event_type=NavigationEventType.FRONT,
        targets=(NavigationTarget.PHONE_FRONT,),
        pulse_count=2,
        pulse_on_ms=_PULSE_ON_MS,
        pulse_off_ms=_PULSE_OFF_MS,
    ),
    NavigationEventType.ARRIVAL: NavigationEventSpec(
        event_type=NavigationEventType.ARRIVAL,
        targets=(),
        pulse_count=0,
        pulse_on_ms=0,
        pulse_off_ms=0,
        implemented=False,
    ),
}

TARGET_TO_NAV_KEY = {
    NavigationTarget.BELT_LEFT: "left",
    NavigationTarget.BELT_RIGHT: "right",
    NavigationTarget.PHONE_FRONT: "phone",
}


def empty_obstacle_command() -> Dict[str, int]:
    return {"left": 0, "front": 0, "right": 0, "back": 0}


def empty_navigation_command() -> Dict[str, int]:
    return {"left": 0, "right": 0, "phone": 0}


def navigation_command_for_event(
    event_type: NavigationEventType,
    intensity: int = 255,
) -> Dict[str, int]:
    """
    Snapshot PWM the mixer would see while a navigation event is "on".

    ARRIVAL is a placeholder: returns all zeros.
    Navigation never sets ESP32 front or back.
    """
    command = empty_navigation_command()
    spec = NAVIGATION_EVENT_SPECS[event_type]
    if not spec.implemented:
        return command
    for target in spec.targets:
        command[TARGET_TO_NAV_KEY[target]] = intensity
    return command


def _pwm(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    if n < 0:
        return 0
    if n > 255:
        return 255
    return n


def mix_obstacle_and_navigation(
    obstacle: Mapping[str, int],
    navigation: Mapping[str, int],
) -> Dict[str, int]:
    """
    Mixer contract: obstacle PWM wins on every belt axis it occupies.

    Output keys
    -----------
    left, front, right, back — ESP32 belt (same shape as GET /cmd today).
    phone — smartphone vibrator for navigation FRONT / START.

    Rules
    -----
    * Belt front and back come only from the obstacle command.
      Navigation ``front`` / ``back`` keys are ignored if present.
    * Belt left/right: if obstacle PWM > 0, keep obstacle; else navigation.
    * Phone is a navigation-only channel; obstacle has no phone axis.
    """
    mixed = {
        "left": _pwm(obstacle.get("left", 0)),
        "front": _pwm(obstacle.get("front", 0)),
        "right": _pwm(obstacle.get("right", 0)),
        "back": _pwm(obstacle.get("back", 0)),
        "phone": 0,
    }

    nav_left = _pwm(navigation.get("left", 0))
    nav_right = _pwm(navigation.get("right", 0))
    nav_phone = _pwm(navigation.get("phone", 0))

    if mixed["left"] == 0:
        mixed["left"] = nav_left
    if mixed["right"] == 0:
        mixed["right"] = nav_right

    mixed["phone"] = nav_phone
    return mixed


def navigation_targets(event_type: NavigationEventType) -> Sequence[NavigationTarget]:
    return NAVIGATION_EVENT_SPECS[event_type].targets
