"""
decision_engine.py
------------------
Decision Engine for HapticGuide.

Responsibilities:
  - Accept a list of RiskObject instances from risk_estimator.py.
  - Map object horizontal regions to motor axes:
      Center -> Front motor
      Left   -> Left motor
      Right  -> Right motor
      Back   -> Back motor
  - Compute PWM intensities (0–255) based on risk scores.
  - Support multi-motor outputs when multiple dangerous objects are present.
  - Update globals.latest_command atomically under command_lock.
"""

from __future__ import annotations

import time
from typing import List, Dict, Optional

from risk_estimator import RiskObject
import globals

# Minimum risk score threshold required to trigger motor vibration (0.0 - 1.0)
MIN_RISK_THRESHOLD: float = 0.25


class DecisionEngine:
    """
    Translates collision risk objects into tactile motor commands (PWM 0–255).
    """

    def __init__(self, min_risk_threshold: float = MIN_RISK_THRESHOLD) -> None:
        self.min_risk_threshold = min_risk_threshold
        self._last_print_time: float = 0.0

    def compute_motor_command(self, risk_objects: List[RiskObject]) -> Dict[str, int]:
        """
        Compute motor command dictionary from RiskObject list and update globals.latest_command.

        Parameters
        ----------
        risk_objects : List[RiskObject]
            List of evaluated risk objects from RiskEstimator.

        Returns
        -------
        Dict[str, int]
            Command dictionary: {"left": int, "front": int, "right": int, "back": int}
        """
        command: Dict[str, int] = {
            "left": 0,
            "front": 0,
            "right": 0,
            "back": 0,
        }

        # Highest risk score per direction axis
        max_risks: Dict[str, float] = {
            "left": 0.0,
            "front": 0.0,
            "right": 0.0,
            "back": 0.0,
        }

        for r_obj in risk_objects:
            if r_obj.risk_score < self.min_risk_threshold:
                continue

            # Map region to motor axis
            region = r_obj.horizontal_region.lower().strip()
            if region == "center":
                axis = "front"
            elif region == "left":
                axis = "left"
            elif region == "right":
                axis = "right"
            elif region == "back":
                axis = "back"
            else:
                axis = "front"

            # Highest risk object in this direction axis wins
            if r_obj.risk_score > max_risks[axis]:
                max_risks[axis] = r_obj.risk_score

        # Convert risk scores to PWM (0 - 255)
        for axis, risk in max_risks.items():
            if risk >= self.min_risk_threshold:
                pwm = int(round(risk * 255.0))
                command[axis] = max(0, min(255, pwm))
            else:
                command[axis] = 0

        # Store command inside globals.latest_command under command_lock
        with globals.command_lock:
            globals.latest_command.update(command)

        # Print debug info every 1 second
        self._print_debug_info(command, max_risks)

        return command

    def _print_debug_info(self, command: Dict[str, int], max_risks: Dict[str, float]) -> None:
        now = time.perf_counter()
        if now - self._last_print_time < 1.0:
            return

        self._last_print_time = now

        active_axes = [f"{k.upper()}={v}" for k, v in command.items() if v > 0]
        cmd_str = ", ".join(active_axes) if active_axes else "SAFE (All 0)"

        print("========================================", flush=True)
        print("Decision Engine Motor Command:", flush=True)
        print(f"  Payload: {command}", flush=True)
        print(f"  Status:  {cmd_str}", flush=True)
        print("========================================", flush=True)


# Singleton DecisionEngine instance
decision_engine = DecisionEngine()


def make_decision(risk_objects: List[RiskObject]) -> Dict[str, int]:
    """Helper function to compute motor command and update globals.latest_command."""
    return decision_engine.compute_motor_command(risk_objects)


if __name__ == "__main__":
    print("Testing DecisionEngine standalone...", flush=True)

    from tracker import TrackedObject

    # Create dummy RiskObject instances
    dummy_t1 = TrackedObject(4, "person", [100, 50, 540, 430], (320.0, 240.0), 167200, 0.93)
    r1 = RiskObject(dummy_t1, 0.93, ["Large object", "Center of image"], 0.2, "center", 5)

    dummy_t2 = TrackedObject(2, "chair", [10, 100, 150, 300], (80.0, 200.0), 28000, 0.82)
    r2 = RiskObject(dummy_t2, 0.65, ["Approaching"], 0.1, "left", 3)

    cmd = decision_engine.compute_motor_command([r1, r2])
    print(f"Computed Command: {cmd}")
    print(f"globals.latest_command: {globals.latest_command}")
    print("DecisionEngine test finished cleanly.", flush=True)
