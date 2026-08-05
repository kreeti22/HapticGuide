"""
object_analyzer.py
-------------------
Object Analyzer layer for HapticGuide.

Responsibilities:
  - Enrich raw DetectedObjects from YOLODetector with metadata:
      * Horizontal Position (LEFT, CENTER, RIGHT)
      * Class Priority (from PRIORITY_TABLE, default=0)
  - Convert every DetectedObject to an AnalyzedObject (no filtering or deletion).
  - Print analyzed object summaries once per second.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Dict, Optional

from detector import DetectedObject
from priority_table import PRIORITY_TABLE, DEFAULT_PRIORITY


@dataclass
class AnalyzedObject:
    """Enriched object metadata container."""
    class_name: str
    confidence: float
    bbox: List[int]       # [x1, y1, x2, y2]
    center_x: float
    center_y: float
    width: int
    height: int
    area: int
    position: str         # "LEFT" | "CENTER" | "RIGHT"
    priority: int         # Priority score (0 - 10)

    @classmethod
    def from_detected_object(
        cls,
        obj: DetectedObject,
        position: str,
        priority: int,
    ) -> AnalyzedObject:
        return cls(
            class_name=obj.class_name,
            confidence=obj.confidence,
            bbox=obj.bbox,
            center_x=obj.center_x,
            center_y=obj.center_y,
            width=obj.width,
            height=obj.height,
            area=obj.area,
            position=position,
            priority=priority,
        )

    def __repr__(self) -> str:
        return (
            f"AnalyzedObject({self.class_name.capitalize()}, "
            f"P={self.priority}, Area={self.area}, Pos={self.position})"
        )


class ObjectAnalyzer:
    """
    Enriches detected objects with metadata (position and priority).
    No filtering or deletion is performed.
    """

    def __init__(self, priority_table: Optional[Dict[str, int]] = None) -> None:
        self.priority_table = priority_table if priority_table is not None else PRIORITY_TABLE
        self._last_print_time: float = 0.0

    def analyze(self, detections: List[DetectedObject], img_width: int = 640) -> List[AnalyzedObject]:
        """
        Enrich all DetectedObject instances into AnalyzedObject instances.

        Parameters
        ----------
        detections : List[DetectedObject]
            Raw detections returned by YOLODetector.
        img_width : int
            Width of current camera frame for horizontal position division.

        Returns
        -------
        List[AnalyzedObject]
            List of metadata-enriched objects.
        """
        analyzed_list: List[AnalyzedObject] = []
        w3 = img_width / 3.0

        for obj in detections:
            # 1. Determine horizontal position (LEFT, CENTER, RIGHT)
            if obj.center_x < w3:
                pos = "LEFT"
            elif obj.center_x < 2 * w3:
                pos = "CENTER"
            else:
                pos = "RIGHT"

            # 2. Lookup priority from PRIORITY_TABLE (default DEFAULT_PRIORITY for unknown classes)
            cls_lower = obj.class_name.lower().strip()
            prio = self.priority_table.get(cls_lower, DEFAULT_PRIORITY)

            # 3. Create AnalyzedObject
            analyzed_list.append(AnalyzedObject.from_detected_object(obj, pos, prio))

        self._print_debug_info(analyzed_list)
        return analyzed_list

    def _print_debug_info(self, objects: List[AnalyzedObject]) -> None:
        now = time.perf_counter()
        if now - self._last_print_time < 1.0:
            return

        self._last_print_time = now

        print("----------------------------------------", flush=True)
        print("Objects Analyzed\n", flush=True)
        if objects:
            for obj in objects:
                print(f"{obj.class_name.capitalize()}", flush=True)
                print(f"Priority:{obj.priority}", flush=True)
                print(f"Area:{obj.area}", flush=True)
                print(f"Position:{obj.position}\n", flush=True)
        else:
            print("None\n", flush=True)
        print("----------------------------------------", flush=True)


# Singleton instance
object_analyzer = ObjectAnalyzer()


def analyze_objects(detections: List[DetectedObject], img_width: int = 640) -> List[AnalyzedObject]:
    """Helper function to analyze detections using default ObjectAnalyzer."""
    return object_analyzer.analyze(detections, img_width)


if __name__ == "__main__":
    print("Testing ObjectAnalyzer standalone...", flush=True)

    dummy_raw = [
        DetectedObject("person", 0.91, [10, 50, 200, 350], 105.0, 200.0, 190, 300, 57000),
        DetectedObject("chair", 0.82, [250, 100, 400, 300], 325.0, 200.0, 150, 200, 30000),
        DetectedObject("bottle", 0.74, [500, 150, 550, 250], 525.0, 200.0, 50, 100, 5000),
    ]

    res = object_analyzer.analyze(dummy_raw, img_width=640)
    print(f"Resulting AnalyzedObjects:\n{res}")
    print("ObjectAnalyzer test finished cleanly.", flush=True)
