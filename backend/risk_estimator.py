"""
risk_estimator.py
------------------
Collision Risk Estimator for HapticGuide.

Responsibilities:
  - Assess collision risk for each TrackedObject based on geometry and dynamics.
  - Evaluate bounding box area, area growth rate, horizontal position, persistence, and motion.
  - Generate a normalized risk_score (0.0 -> 1.0) and human-readable risk reasons.
  - Does NOT implement motor control or hardware logic.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional

from tracker import TrackedObject


@dataclass
class RiskObject:
    """Tracked object enriched with collision risk metrics and explanatory reasons."""
    tracked_object: TrackedObject
    risk_score: float                # Bounded score between 0.0 and 1.0
    reasons: List[str]               # Primary factors contributing to the risk score
    area_growth_rate: float          # Relative area growth rate (% change)
    horizontal_region: str           # "left" | "center" | "right"
    persistence_frames: int          # Number of consecutive frames tracked

    @property
    def id(self) -> int:
        return self.tracked_object.id

    @property
    def class_name(self) -> str:
        return self.tracked_object.class_name

    @property
    def bbox(self) -> List[int]:
        return self.tracked_object.bbox

    @property
    def center(self) -> Tuple[float, float]:
        return self.tracked_object.center

    @property
    def area(self) -> int:
        return self.tracked_object.area

    @property
    def confidence(self) -> float:
        return self.tracked_object.confidence

    def __repr__(self) -> str:
        reason_str = " | ".join(self.reasons) if self.reasons else "Low risk"
        return (
            f"RiskObject({self.class_name} #{self.id}, Risk={self.risk_score:.2f}, "
            f"Region={self.horizontal_region}, Reasons=[{reason_str}])"
        )


class TrackState:
    """Internal temporal history for a single object track ID."""

    def __init__(self, initial_obj: TrackedObject) -> None:
        self.track_id: int = initial_obj.id
        self.class_name: str = initial_obj.class_name
        self.area_history: List[int] = [initial_obj.area]
        self.center_history: List[Tuple[float, float]] = [initial_obj.center]
        self.persistence_frames: int = 1
        self.last_seen_time: float = time.perf_counter()

    def update(self, obj: TrackedObject) -> None:
        self.area_history.append(obj.area)
        self.center_history.append(obj.center)
        if len(self.area_history) > 10:
            self.area_history.pop(0)
            self.center_history.pop(0)
        self.persistence_frames += 1
        self.last_seen_time = time.perf_counter()

    @property
    def area_growth_rate(self) -> float:
        """Percentage growth of bounding box area over history."""
        if len(self.area_history) < 2:
            return 0.0
        initial_area = self.area_history[0]
        latest_area = self.area_history[-1]
        if initial_area <= 0:
            return 0.0
        return (latest_area - initial_area) / float(initial_area)

    @property
    def motion_vector(self) -> Tuple[float, float]:
        """Motion displacement vector (dx, dy) over history."""
        if len(self.center_history) < 2:
            return (0.0, 0.0)
        c_start = self.center_history[0]
        c_latest = self.center_history[-1]
        return (c_latest[0] - c_start[0], c_latest[1] - c_start[1])


class RiskEstimator:
    """
    Evaluates collision risk for incoming TrackedObjects.
    Calculates metrics for area, growth, horizontal position, persistence, and motion.
    """

    def __init__(self, max_history_age: float = 3.0) -> None:
        self.max_history_age = max_history_age
        self.track_histories: Dict[int, TrackState] = {}
        self._last_print_time: float = 0.0

    def estimate_risk(
        self,
        tracked_objects: List[TrackedObject],
        frame_width: int = 640,
        frame_height: int = 480,
    ) -> List[RiskObject]:
        """
        Assess risk scores for a list of tracked objects on a frame.

        Parameters
        ----------
        tracked_objects : List[TrackedObject]
            Output list of TrackedObject instances from ByteTracker.
        frame_width : int
            Width of current camera frame.
        frame_height : int
            Height of current camera frame.

        Returns
        -------
        List[RiskObject]
            Objects enriched with risk scores (0.0 -> 1.0) and explanatory reasons.
        """
        now = time.perf_counter()

        # Update track histories & prune stale entries
        active_ids = set()
        for obj in tracked_objects:
            active_ids.add(obj.id)
            if obj.id in self.track_histories:
                self.track_histories[obj.id].update(obj)
            else:
                self.track_histories[obj.id] = TrackState(obj)

        stale_ids = [
            tid
            for tid, state in self.track_histories.items()
            if tid not in active_ids and (now - state.last_seen_time) > self.max_history_age
        ]
        for tid in stale_ids:
            del self.track_histories[tid]

        risk_objects: List[RiskObject] = []
        frame_area = float(max(1, frame_width * frame_height))

        for obj in tracked_objects:
            history = self.track_histories[obj.id]
            risk_score, reasons, region, growth_rate = self._compute_object_risk(
                obj, history, frame_width, frame_height, frame_area
            )

            risk_objects.append(
                RiskObject(
                    tracked_object=obj,
                    risk_score=risk_score,
                    reasons=reasons,
                    area_growth_rate=growth_rate,
                    horizontal_region=region,
                    persistence_frames=history.persistence_frames,
                )
            )

        # Sort by risk score descending
        risk_objects.sort(key=lambda r: r.risk_score, reverse=True)

        # Print debug logging
        self._print_debug_info(risk_objects)

        return risk_objects

    def _compute_object_risk(
        self,
        obj: TrackedObject,
        history: TrackState,
        frame_w: int,
        frame_h: int,
        frame_area: float,
    ) -> Tuple[float, List[str], str, float]:
        reasons: List[str] = []

        # 1. Area Factor (Closer / Larger objects take more frame area)
        area_ratio = obj.area / frame_area
        # Scale: 20% or more of frame is considered a large object
        area_risk = min(1.0, area_ratio / 0.20)
        if area_ratio >= 0.15:
            reasons.append("Large object")

        # 2. Bounding Box Growth Factor (Expanding area indicates approaching obstacle)
        growth_rate = history.area_growth_rate
        if growth_rate >= 0.15:
            growth_risk = 1.0
            reasons.append("Growing rapidly")
        elif growth_rate >= 0.05:
            growth_risk = 0.5
            reasons.append("Approaching")
        else:
            growth_risk = 0.0

        # 3. Horizontal Position Factor (Center of image is directly in walking path)
        cx, cy = obj.center
        rel_x = cx / float(frame_w) if frame_w > 0 else 0.5

        if 0.30 <= rel_x <= 0.70:
            region = "center"
            pos_risk = 1.0
            reasons.append("Center of image")
        elif rel_x < 0.30:
            region = "left"
            pos_risk = 0.4
        else:
            region = "right"
            pos_risk = 0.4

        # 4. Persistence Factor (More persistent tracks have higher confidence)
        persist_factor = min(1.0, history.persistence_frames / 3.0)

        # 5. Motion Vector Factor
        dx, dy = history.motion_vector
        motion_speed = math.sqrt(dx * dx + dy * dy)
        motion_risk = min(1.0, motion_speed / 50.0)

        # Weighted combination
        raw_score = (
            0.35 * area_risk
            + 0.30 * growth_risk
            + 0.25 * pos_risk
            + 0.10 * motion_risk
        ) * persist_factor

        # Clamp score between 0.0 and 1.0
        final_risk = max(0.0, min(1.0, round(raw_score, 2)))

        return final_risk, reasons, region, growth_rate

    def _print_debug_info(self, risk_objects: List[RiskObject]) -> None:
        now = time.perf_counter()
        if now - self._last_print_time < 1.0:
            return

        self._last_print_time = now

        if not risk_objects:
            print("========================================", flush=True)
            print("Object: None", flush=True)
            print("Risk:   0.00", flush=True)
            print("Reason: No active obstacles", flush=True)
            print("========================================", flush=True)
            return

        # Print top risk object
        top = risk_objects[0]
        reason_str = "\n  ".join(top.reasons) if top.reasons else "Low risk obstacle"

        print("========================================", flush=True)
        print(f"Object: {top.class_name.capitalize()} #{top.id}", flush=True)
        print(f"Risk:   {top.risk_score:.2f}", flush=True)
        print(f"Reason: \n  {reason_str}", flush=True)
        print("========================================", flush=True)


# Singleton risk estimator instance
risk_estimator = RiskEstimator()


def estimate_risk(
    tracked_objects: List[TrackedObject],
    frame_width: int = 640,
    frame_height: int = 480,
) -> List[RiskObject]:
    """Helper function to calculate risk for tracked objects."""
    return risk_estimator.estimate_risk(tracked_objects, frame_width, frame_height)


if __name__ == "__main__":
    print("Testing RiskEstimator standalone...", flush=True)

    dummy_t1 = TrackedObject(
        id=4,
        class_name="person",
        bbox=[100, 50, 540, 430],
        center=(320.0, 240.0),
        area=167200,
        confidence=0.93,
    )

    # Initial assessment
    risks = risk_estimator.estimate_risk([dummy_t1])

    # Simulate growth on frame 2
    dummy_t2 = TrackedObject(
        id=4,
        class_name="person",
        bbox=[80, 30, 560, 450],
        center=(320.0, 240.0),
        area=201600,
        confidence=0.95,
    )
    risks = risk_estimator.estimate_risk([dummy_t2])

    print(f"Resulting RiskObjects: {risks}", flush=True)
    print("RiskEstimator test finished cleanly.", flush=True)
