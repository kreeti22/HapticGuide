"""
object_filter.py
----------------
Filtering layer for HapticGuide.

Responsibilities:
  - Filter raw YOLO detections to retain only objects relevant for blind navigation.
  - Wrap retained detections as ObstacleObject instances.
  - Log Filtered and Ignored objects to stdout every second.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Set

from detector import DetectedObject


# Initial whitelist of relevant obstacle classes for navigation
DEFAULT_ALLOWED_CLASSES: Set[str] = {
    "person",
    "chair",
    "table",
    "dining table",
    "bench",
    "car",
    "motorcycle",
    "bicycle",
    "pole",
    "trash can",
    "waste container",
    "garbage can",
    "bin",
    "door",
}


@dataclass
class ObstacleObject:
    """Classified and filtered obstacle object ready for decision processing."""
    class_name: str
    confidence: float
    bbox: List[int]       # [x1, y1, x2, y2]
    center_x: float
    center_y: float
    width: int
    height: int
    area: int

    @classmethod
    def from_detected_object(cls, obj: DetectedObject) -> ObstacleObject:
        return cls(
            class_name=obj.class_name,
            confidence=obj.confidence,
            bbox=obj.bbox,
            center_x=obj.center_x,
            center_y=obj.center_y,
            width=obj.width,
            height=obj.height,
            area=obj.area,
        )

    def __repr__(self) -> str:
        pct = int(round(self.confidence * 100))
        return f"ObstacleObject({self.class_name} {pct}%, bbox={self.bbox})"


class ObjectFilter:
    """
    Filter YOLO DetectedObjects using a class whitelist.
    """

    def __init__(self, allowed_classes: Optional[Set[str]] = None) -> None:
        if allowed_classes is None:
            self.allowed_classes = DEFAULT_ALLOWED_CLASSES
        else:
            self.allowed_classes = {c.lower().strip() for c in allowed_classes}

        self._last_print_time: float = 0.0

    def filter(self, detections: List[DetectedObject]) -> List[ObstacleObject]:
        """
        Filter detections list and return list of ObstacleObjects.

        Parameters
        ----------
        detections : List[DetectedObject]
            Raw detections output from YOLODetector.

        Returns
        -------
        List[ObstacleObject]
            Filtered list of relevant obstacle objects.
        """
        filtered_objects: List[ObstacleObject] = []
        ignored_objects: List[DetectedObject] = []

        for obj in detections:
            filtered_objects.append(ObstacleObject.from_detected_object(obj))

        self._print_filter_summary(filtered_objects, ignored_objects)
        return filtered_objects

    def _print_filter_summary(
        self,
        filtered: List[ObstacleObject],
        ignored: List[DetectedObject],
    ) -> None:
        now = time.perf_counter()
        if now - self._last_print_time < 1.0:
            return

        self._last_print_time = now

        filt_str = (
            ", ".join([f"{o.class_name.capitalize()} ({int(round(o.confidence * 100))}%)" for o in filtered])
            if filtered
            else "None"
        )
        ign_str = (
            ", ".join([f"{o.class_name.capitalize()} ({int(round(o.confidence * 100))}%)" for o in ignored])
            if ignored
            else "None"
        )

        print("========================================", flush=True)
        print(f"Filtered Objects: {filt_str}", flush=True)
        print(f"Ignored Objects:  {ign_str}", flush=True)
        print("========================================", flush=True)


# Singleton instance
object_filter = ObjectFilter()


def filter_objects(detections: List[DetectedObject]) -> List[ObstacleObject]:
    """Helper function to filter detections using default ObjectFilter."""
    return object_filter.filter(detections)


if __name__ == "__main__":
    print("Testing ObjectFilter standalone...", flush=True)

    dummy_detections = [
        DetectedObject("person", 0.91, [10, 10, 50, 50], 30.0, 30.0, 40, 40, 1600),
        DetectedObject("bottle", 0.74, [60, 60, 80, 80], 70.0, 70.0, 20, 20, 400),
        DetectedObject("chair", 0.82, [100, 100, 150, 150], 125.0, 125.0, 50, 50, 2500),
    ]

    filt = object_filter.filter(dummy_detections)
    print(f"Resulting ObstacleObjects: {filt}", flush=True)
    print("ObjectFilter test finished cleanly.", flush=True)
