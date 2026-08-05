"""
target_selector.py
------------------
Selects ONE target obstacle from all AnalyzedObjects.

Responsibilities
----------------
  - Accept List[AnalyzedObject] from ObjectAnalyzer.
  - Apply a selection rule and return ONE SelectedTarget.
  - Return None when no objects are present.
  - Print a summary once per second.

Does NOT
--------
  - Filter or remove any detection.
  - Estimate collision risk.
  - Control motors.
  - Perform tracking.

Rule Version 1
--------------
  Select the AnalyzedObject with the largest bounding box area.
  Confidence and priority are intentionally ignored at this stage.
  The selection reason is always "Largest Bounding Box".

Output type: SelectedTarget (dataclass)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

from object_analyzer import AnalyzedObject


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class SelectedTarget:
    """
    Single obstacle selected from the full analyzed-object list.

    All fields are copied directly from the source AnalyzedObject so
    downstream consumers never need to import AnalyzedObject themselves.
    """
    class_name: str
    area:       int
    position:   str     # "LEFT" | "CENTER" | "RIGHT"
    priority:   int
    center_x:   float
    center_y:   float
    bbox:       List[int]   # [x1, y1, x2, y2]
    confidence: float
    reason:     str     # human-readable selection reason

    @classmethod
    def from_analyzed(cls, obj: AnalyzedObject, reason: str) -> "SelectedTarget":
        return cls(
            class_name = obj.class_name,
            area       = obj.area,
            position   = obj.position,
            priority   = obj.priority,
            center_x   = obj.center_x,
            center_y   = obj.center_y,
            bbox       = obj.bbox,
            confidence = obj.confidence,
            reason     = reason,
        )

    def __repr__(self) -> str:
        return (
            f"SelectedTarget({self.class_name.capitalize()}, "
            f"Area={self.area}, Pos={self.position}, "
            f"Reason='{self.reason}')"
        )


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------

class TargetSelector:
    """
    Selects the single most important obstacle from analyzed detections.

    Rule Version 1: largest bounding box area wins.
    """

    def __init__(self) -> None:
        self._last_print_time: float = 0.0

    def select(self, analyzed: List[AnalyzedObject]) -> Optional[SelectedTarget]:
        """
        Select ONE target from *analyzed*.

        Parameters
        ----------
        analyzed : List[AnalyzedObject]
            Full output of ObjectAnalyzer.analyze().  Not modified.

        Returns
        -------
        SelectedTarget | None
            The selected target, or None if the list is empty.
        """
        if not analyzed:
            self._print_debug([], None)
            return None

        # Rule V1: largest bounding box area — O(n) single pass
        best = max(analyzed, key=lambda obj: obj.area)
        target = SelectedTarget.from_analyzed(best, reason="Largest Bounding Box")

        self._print_debug(analyzed, target)
        return target

    # -------------------------------------------------------------------------
    # Debug output
    # -------------------------------------------------------------------------

    def _print_debug(
        self,
        analyzed:   List[AnalyzedObject],
        target:     Optional[SelectedTarget],
    ) -> None:
        """Print selection summary at most once per second."""
        now = time.perf_counter()
        if now - self._last_print_time < 1.0:
            return
        self._last_print_time = now

        print("----------------------------------------", flush=True)
        print("TARGET SELECTOR\n", flush=True)

        # All detected objects
        print("Detected", flush=True)
        if analyzed:
            for obj in analyzed:
                print(
                    f"  {obj.class_name.capitalize():<20} Area {obj.area}",
                    flush=True,
                )
        else:
            print("  None", flush=True)

        print("", flush=True)

        # Selected target
        if target is not None:
            print("Selected", flush=True)
            print(f"  {target.class_name.capitalize()}", flush=True)
            print("Reason", flush=True)
            print(f"  {target.reason}", flush=True)
        else:
            print("Selected", flush=True)
            print("  None", flush=True)

        print("----------------------------------------", flush=True)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

target_selector = TargetSelector()
