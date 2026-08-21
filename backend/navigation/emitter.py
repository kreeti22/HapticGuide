"""
emitter.py
----------
Navigation haptic pulse emitter and obstacle mixer integration (Phase 6).

Translates Phase 5 navigation decisions into precise haptic pulse sequences
following the Phase 0 contract:
  - NAVIGATION_START: 3 pulses on belt-left, belt-right, and phone-front
  - NAVIGATION_LEFT: 2 pulses on belt-left
  - NAVIGATION_RIGHT: 2 pulses on belt-right
  - NAVIGATION_FRONT: 2 pulses on phone-front
  - NAVIGATION_ARRIVAL: placeholder event

Guarantees:
  - Obstacle detection has absolute priority on occupied belt axes.
  - Navigation NEVER sets ESP32 'front' or 'back' (which belong solely to obstacle detection).
  - Phone-front vibration is an independent channel for the smartphone.
  - Maneuver pulses are deduplicated and emitted exactly once per route step.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from navigation.contract import (
    NAVIGATION_EVENT_SPECS,
    TARGET_TO_NAV_KEY,
    NavigationEventSpec,
    NavigationEventType,
    NavigationTarget,
    empty_navigation_command,
    mix_obstacle_and_navigation,
)
from navigation.follower import RouteProgress
from navigation.state import NavigationState, NavigationStatus

logger = logging.getLogger(__name__)


@dataclass
class ActivePulseSequence:
    """Represents a scheduled, multi-pulse haptic waveform in real time."""

    event_type: NavigationEventType
    targets: Tuple[NavigationTarget, ...]
    pulse_count: int
    pulse_on_ms: int
    pulse_off_ms: int
    started_at_s: float

    @property
    def duration_s(self) -> float:
        if self.pulse_count <= 0:
            return 0.0
        total_ms = (self.pulse_count * self.pulse_on_ms) + (
            (self.pulse_count - 1) * self.pulse_off_ms
        )
        return total_ms / 1000.0

    def is_active(self, now_s: float) -> bool:
        if self.pulse_count <= 0:
            return False
        elapsed_s = now_s - self.started_at_s
        return 0.0 <= elapsed_s < self.duration_s

    def is_in_on_pulse(self, now_s: float) -> bool:
        if self.pulse_count <= 0:
            return False
        elapsed_ms = (now_s - self.started_at_s) * 1000.0
        if elapsed_ms < 0.0 or elapsed_ms >= self.duration_s * 1000.0:
            return False
        period_ms = self.pulse_on_ms + self.pulse_off_ms
        phase_ms = elapsed_ms % period_ms
        return phase_ms < self.pulse_on_ms

    def get_target_pwm(self, now_s: float, intensity: int = 255) -> Dict[str, int]:
        cmd = empty_navigation_command()
        if self.is_in_on_pulse(now_s):
            for target in self.targets:
                key = TARGET_TO_NAV_KEY.get(target)
                if key:
                    cmd[key] = intensity
        return cmd


def event_for_maneuver_code(maneuver: Optional[str]) -> Optional[NavigationEventType]:
    """Map high-level maneuver token to NavigationEventType."""
    if not maneuver:
        return None
    key = maneuver.strip().upper()
    if key == "LEFT":
        return NavigationEventType.LEFT
    if key == "RIGHT":
        return NavigationEventType.RIGHT
    if key in ("FRONT", "STRAIGHT"):
        return NavigationEventType.FRONT
    if key in ("ARRIVAL", "ARRIVE"):
        return NavigationEventType.ARRIVAL
    return None


class NavigationHapticEmitter:
    """
    Manages navigation event emission, deduplication per route step, and pulse timing.
    """

    def __init__(self, state: Optional[NavigationState] = None) -> None:
        self._state = state
        self._lock = threading.Lock()
        self._start_emitted: bool = False
        self._emitted_step_indices: set[int] = set()
        self._arrival_emitted: bool = False
        self._active_sequence: Optional[ActivePulseSequence] = None
        self._event_history: List[Tuple[float, NavigationEventType, int]] = []

    def play_event(
        self,
        event_type: NavigationEventType,
        now: Optional[float] = None,
        intensity: int = 255,
    ) -> ActivePulseSequence:
        """Schedule and start playing a navigation haptic event."""
        clock = time.monotonic() if now is None else now
        spec = NAVIGATION_EVENT_SPECS[event_type]

        seq = ActivePulseSequence(
            event_type=event_type,
            targets=spec.targets,
            pulse_count=spec.pulse_count,
            pulse_on_ms=spec.pulse_on_ms,
            pulse_off_ms=spec.pulse_off_ms,
            started_at_s=clock,
        )

        with self._lock:
            self._active_sequence = seq
            self._event_history.append((clock, event_type, spec.pulse_count))
            if self._state is not None:
                self._state.pending_haptic_event = event_type

        logger.info(
            "Emitted %s (%d pulses on %s)",
            event_type.value,
            spec.pulse_count,
            [t.value for t in spec.targets],
        )
        return seq

    def evaluate_and_emit(
        self,
        state: NavigationState,
        progress: RouteProgress,
        now: Optional[float] = None,
    ) -> Optional[NavigationEventType]:
        """
        Evaluate route progress and emit deduplicated navigation events.
        """
        clock = time.monotonic() if now is None else now

        with self._lock:
            # 1. NAVIGATION_START once per active navigation session
            if (
                not self._start_emitted
                and progress.active
                and state.status in (NavigationStatus.NAVIGATING, NavigationStatus.ROUTE_READY)
            ):
                self._start_emitted = True
                self._play_event_unlocked(NavigationEventType.START, clock)
                return NavigationEventType.START

            # 2. Destination Arrival
            if progress.is_arrived:
                if not self._arrival_emitted:
                    self._arrival_emitted = True
                    self._play_event_unlocked(NavigationEventType.ARRIVAL, clock)
                    return NavigationEventType.ARRIVAL
                return None

            # 3. Upcoming Maneuver (deduplicated per route step index)
            if progress.is_maneuver_imminent:
                step_idx = progress.current_step_index
                if step_idx not in self._emitted_step_indices:
                    self._emitted_step_indices.add(step_idx)
                    event_type = event_for_maneuver_code(progress.next_maneuver)
                    if event_type is not None:
                        self._play_event_unlocked(event_type, clock)
                        return event_type

        return None

    def _play_event_unlocked(
        self,
        event_type: NavigationEventType,
        now: float,
        intensity: int = 255,
    ) -> ActivePulseSequence:
        spec = NAVIGATION_EVENT_SPECS[event_type]
        seq = ActivePulseSequence(
            event_type=event_type,
            targets=spec.targets,
            pulse_count=spec.pulse_count,
            pulse_on_ms=spec.pulse_on_ms,
            pulse_off_ms=spec.pulse_off_ms,
            started_at_s=now,
        )
        self._active_sequence = seq
        self._event_history.append((now, event_type, spec.pulse_count))
        if self._state is not None:
            self._state.pending_haptic_event = event_type
        return seq

    def get_navigation_pwm(self, now: Optional[float] = None) -> Dict[str, int]:
        """
        Return active navigation PWM for belt left, right, and phone.
        Never sets ESP32 front or back.
        """
        clock = time.monotonic() if now is None else now
        with self._lock:
            if self._active_sequence is not None and self._active_sequence.is_active(clock):
                return self._active_sequence.get_target_pwm(clock)
        return empty_navigation_command()

    def mix_with_obstacle(
        self,
        obstacle_cmd: Mapping[str, int],
        now: Optional[float] = None,
    ) -> Dict[str, int]:
        """Mix obstacle PWM with active navigation pulse sequence."""
        nav_pwm = self.get_navigation_pwm(now=now)
        return mix_obstacle_and_navigation(obstacle_cmd, nav_pwm)

    def get_event_history(self) -> List[Tuple[float, NavigationEventType, int]]:
        with self._lock:
            return list(self._event_history)

    def reset(self) -> None:
        """Reset emitter state, clear pulse queues and deduplication sets."""
        with self._lock:
            self._start_emitted = False
            self._emitted_step_indices.clear()
            self._arrival_emitted = False
            self._active_sequence = None
            self._event_history.clear()


_GLOBAL_EMITTER: Optional[NavigationHapticEmitter] = None
_GLOBAL_EMITTER_LOCK = threading.Lock()


def get_emitter(state: Optional[NavigationState] = None) -> NavigationHapticEmitter:
    """Get or initialize the process-wide NavigationHapticEmitter."""
    global _GLOBAL_EMITTER
    with _GLOBAL_EMITTER_LOCK:
        if _GLOBAL_EMITTER is None:
            _GLOBAL_EMITTER = NavigationHapticEmitter(state=state)
        elif state is not None and _GLOBAL_EMITTER._state is None:
            _GLOBAL_EMITTER._state = state
        return _GLOBAL_EMITTER


def get_mixed_command(
    obstacle_cmd: Mapping[str, int],
    now: Optional[float] = None,
) -> Dict[str, int]:
    """
    Produce final 4-axis belt command {left, front, right, back} for GET /cmd,
    mixing active obstacle PWM with active navigation pulses according to contract.
    """
    emitter = get_emitter()
    mixed = emitter.mix_with_obstacle(obstacle_cmd, now=now)
    # Return 4-axis belt command format for ESP32
    return {
        "left": mixed.get("left", 0),
        "front": mixed.get("front", 0),
        "right": mixed.get("right", 0),
        "back": mixed.get("back", 0),
    }
