"""
decision_engine.py
------------------
Decision Engine for HapticGuide.

Responsibilities:
  - Accept the selected target from target_selector.py.
  - Map the target position to a single motor command.
  - LEFT   -> left motor
  - CENTER -> front motor
  - RIGHT  -> right motor
  - BACK   -> back motor
  - Inactive motors remain 0.
  - Update globals.latest_command atomically under command_lock.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from target_selector import SelectedTarget
import globals


class DecisionEngine:
    """
    Translates a SelectedTarget into a simple motor command.

    Version 1 logic:
      LEFT   -> left=255
      CENTER -> front=255
      RIGHT  -> right=255
      BACK   -> back=255
      inactive motors remain 0.
    """

    def __init__(self) -> None:
        self._last_print_time: float = 0.0

    def compute_motor_command(self, selected_target: Optional[SelectedTarget]) -> Dict[str, int]:
        """
        Compute motor command dictionary from a SelectedTarget and update globals.latest_command.

        Parameters
        ----------
        selected_target : Optional[SelectedTarget]
            The single selected target returned by the TargetSelector.

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

        if selected_target is not None:
            position = selected_target.position.strip().upper()
            if position == "LEFT":
                command["left"] = 255
            elif position == "CENTER":
                command["front"] = 255
            elif position == "RIGHT":
                command["right"] = 255
            elif position == "BACK":
                command["back"] = 255

        with globals.command_lock:
            globals.latest_command.update(command)

        self._print_debug_info(selected_target, command)

        return command

    def _print_debug_info(
        self,
        selected_target: Optional[SelectedTarget],
        command: Dict[str, int],
    ) -> None:
        now = time.perf_counter()
        if now - self._last_print_time < 1.0:
            return

        self._last_print_time = now

        print("========================================", flush=True)
        print("Selected Target:", flush=True)
        if selected_target is not None:
            print(f"  Class:    {selected_target.class_name}", flush=True)
            print(f"  Position: {selected_target.position}", flush=True)
        else:
            print("  None", flush=True)
        print("Generated Command:", flush=True)
        print(f"  {command}", flush=True)
        print("========================================", flush=True)


# Singleton DecisionEngine instance
decision_engine = DecisionEngine()


def make_decision(selected_target: Optional[SelectedTarget]) -> Dict[str, int]:
    """Helper function to compute motor command and update globals.latest_command."""
    return decision_engine.compute_motor_command(selected_target)


if __name__ == "__main__":
    print("Testing DecisionEngine standalone...", flush=True)

    from target_selector import SelectedTarget

    dummy_target = SelectedTarget(
        class_name="person",
        area=167200,
        position="CENTER",
        priority=5,
        center_x=320.0,
        center_y=240.0,
        bbox=[100, 50, 540, 430],
        confidence=0.93,
        reason="Manual test"
    )

    cmd = decision_engine.compute_motor_command(dummy_target)
    print(f"Computed Command: {cmd}")
    print(f"globals.latest_command: {globals.latest_command}")
    print("DecisionEngine test finished cleanly.", flush=True)
