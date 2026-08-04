"""
tracker.py
----------
ByteTrack Object Tracker for HapticGuide.

Responsibilities:
  - Maintain stable unique IDs across consecutive video frames using ByteTrack algorithm.
  - Accept a list of ObstacleObjects from object_filter.py.
  - Associate detections using two-stage IoU matching and constant-velocity state estimation.
  - Return a list of TrackedObject instances.
  - Log Tracking FPS, Active Tracks, and Track IDs to stdout every second.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Tuple, Optional

import numpy as np

from object_filter import ObstacleObject


@dataclass
class TrackedObject:
    """Tracked object with a stable frame-to-frame ID."""
    id: int
    class_name: str
    bbox: List[int]             # [x1, y1, x2, y2]
    center: Tuple[float, float] # (center_x, center_y)
    area: int
    confidence: float

    def __repr__(self) -> str:
        pct = int(round(self.confidence * 100))
        return (
            f"TrackedObject({self.class_name} #{self.id} {pct}%, "
            f"bbox={self.bbox}, center=({self.center[0]:.1f}, {self.center[1]:.1f}))"
        )


def _compute_iou(box1: List[int], box2: List[int]) -> float:
    """Compute Intersection over Union (IoU) between two bounding boxes [x1, y1, x2, y2]."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter_area = inter_w * inter_h

    area1 = max(0, box1[2] - box1[0]) * max(0, box1[3] - box1[1])
    area2 = max(0, box2[2] - box2[0]) * max(0, box2[3] - box2[1])

    union_area = area1 + area2 - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / float(union_area)


class Track:
    """Individual object track maintained across frames."""

    def __init__(self, track_id: int, obj: ObstacleObject) -> None:
        self.track_id: int = track_id
        self.class_name: str = obj.class_name
        self.bbox: List[int] = list(obj.bbox)
        self.center: Tuple[float, float] = (obj.center_x, obj.center_y)
        self.area: int = obj.area
        self.confidence: float = obj.confidence

        self.time_since_update: int = 0
        self.hits: int = 1
        self.age: int = 1

        # Velocity components (dx, dy) for motion prediction
        self.vx: float = 0.0
        self.vy: float = 0.0

    def predict(self) -> List[int]:
        """Simple constant-velocity position prediction."""
        x1, y1, x2, y2 = self.bbox
        pred_x1 = int(round(x1 + self.vx))
        pred_y1 = int(round(y1 + self.vy))
        pred_x2 = int(round(x2 + self.vx))
        pred_y2 = int(round(y2 + self.vy))
        return [pred_x1, pred_y1, pred_x2, pred_y2]

    def update(self, obj: ObstacleObject) -> None:
        """Update track state with a matched detection."""
        new_cx = obj.center_x
        new_cy = obj.center_y

        # Exponential smoothing on velocity
        self.vx = 0.7 * self.vx + 0.3 * (new_cx - self.center[0])
        self.vy = 0.7 * self.vy + 0.3 * (new_cy - self.center[1])

        self.class_name = obj.class_name
        self.bbox = list(obj.bbox)
        self.center = (new_cx, new_cy)
        self.area = obj.area
        self.confidence = obj.confidence

        self.time_since_update = 0
        self.hits += 1
        self.age += 1

    def to_tracked_object(self) -> TrackedObject:
        return TrackedObject(
            id=self.track_id,
            class_name=self.class_name,
            bbox=list(self.bbox),
            center=self.center,
            area=self.area,
            confidence=self.confidence,
        )


class ByteTracker:
    """
    ByteTrack implementation for multi-object tracking.
    Uses two-stage association (high-score & low-score detections)
    to maintain stable track IDs across frames.
    """

    def __init__(
        self,
        high_thresh: float = 0.4,
        match_thresh: float = 0.2,
        max_age: int = 30,
    ) -> None:
        self.high_thresh = high_thresh
        self.match_thresh = match_thresh
        self.max_age = max_age

        self._next_id: int = 1
        self.tracks: List[Track] = []

        # Perf tracking
        self._frame_count: int = 0
        self._fps_window_start: float = 0.0
        self._tracking_fps: float = 0.0
        self._last_print_time: float = 0.0

    def update(self, objects: List[ObstacleObject]) -> List[TrackedObject]:
        """
        Process a frame's obstacle objects and return tracked objects with stable IDs.
        """
        # Step 1: Predict new locations for active tracks
        for trk in self.tracks:
            trk.time_since_update += 1
            trk.age += 1

        # Step 2: Separate high-score and low-score detections (ByteTrack principle)
        high_dets: List[ObstacleObject] = []
        low_dets: List[ObstacleObject] = []

        for obj in objects:
            if obj.confidence >= self.high_thresh:
                high_dets.append(obj)
            else:
                low_dets.append(obj)

        # Step 3: First association stage — match active tracks with high-score detections
        unmatched_tracks, unmatched_high_dets = self._associate(
            self.tracks, high_dets, self.match_thresh
        )

        # Step 4: Second association stage — match remaining tracks with low-score detections
        sub_tracks = [self.tracks[i] for i in unmatched_tracks]
        unmatched_sub_tracks, _ = self._associate(
            sub_tracks, low_dets, self.match_thresh
        )

        # Step 5: Initialize new tracks for unmatched high-score detections
        for det_idx in unmatched_high_dets:
            new_track = Track(self._next_id, high_dets[det_idx])
            self._next_id += 1
            self.tracks.append(new_track)

        # Step 6: Prune old dead tracks
        self.tracks = [
            t for t in self.tracks if t.time_since_update <= self.max_age
        ]

        # Step 7: Build output list of active tracked objects
        tracked_objects: List[TrackedObject] = [
            t.to_tracked_object() for t in self.tracks if t.time_since_update == 0
        ]

        # Performance & debug tracking
        self._update_fps()
        self._print_debug_info(tracked_objects)

        return tracked_objects

    def _associate(
        self,
        tracks: List[Track],
        detections: List[ObstacleObject],
        iou_threshold: float,
    ) -> Tuple[List[int], List[int]]:
        """
        Greedy IoU bipartite matching between tracks and detections.
        Returns (unmatched_track_indices, unmatched_detection_indices).
        """
        if not tracks or not detections:
            return list(range(len(tracks))), list(range(len(detections)))

        # Build IoU cost matrix
        iou_matrix = np.zeros((len(tracks), len(detections)), dtype=np.float32)
        for i, trk in enumerate(tracks):
            pred_box = trk.predict()
            for j, det in enumerate(detections):
                score = _compute_iou(pred_box, det.bbox)
                if trk.class_name == det.class_name:
                    score += 0.1  # bonus for class match
                iou_matrix[i, j] = score

        unmatched_tracks = set(range(len(tracks)))
        unmatched_dets = set(range(len(detections)))

        # Greedy match highest IoU pairs
        while True:
            if iou_matrix.size == 0:
                break
            max_val = np.max(iou_matrix)
            if max_val < iou_threshold:
                break

            i, j = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
            unmatched_tracks.discard(int(i))
            unmatched_dets.discard(int(j))

            tracks[i].update(detections[j])

            iou_matrix[i, :] = -1.0
            iou_matrix[:, j] = -1.0

        return sorted(list(unmatched_tracks)), sorted(list(unmatched_dets))

    def _update_fps(self) -> None:
        now = time.perf_counter()
        if self._fps_window_start == 0.0:
            self._fps_window_start = now
            return

        self._frame_count += 1
        elapsed = now - self._fps_window_start
        if elapsed >= 1.0:
            self._tracking_fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_window_start = now

    def _print_debug_info(self, tracked_objects: List[TrackedObject]) -> None:
        now = time.perf_counter()
        if now - self._last_print_time < 1.0:
            return

        self._last_print_time = now

        track_ids_str = (
            ", ".join([f"{o.class_name.capitalize()} #{o.id}" for o in tracked_objects])
            if tracked_objects
            else "None"
        )

        print("========================================", flush=True)
        print(f"Tracking FPS:  {self._tracking_fps:.1f}", flush=True)
        print(f"Active Tracks: {len(tracked_objects)}", flush=True)
        print(f"Track IDs:     {track_ids_str}", flush=True)
        print("========================================", flush=True)


# Singleton tracker instance
byte_tracker = ByteTracker()


def track_objects(objects: List[ObstacleObject]) -> List[TrackedObject]:
    """Helper function to update tracker with new ObstacleObjects."""
    return byte_tracker.update(objects)


if __name__ == "__main__":
    print("Testing ByteTracker standalone...", flush=True)

    dummy1 = [
        ObstacleObject("person", 0.91, [10, 10, 50, 50], 30.0, 30.0, 40, 40, 1600),
        ObstacleObject("chair", 0.82, [100, 100, 150, 150], 125.0, 125.0, 50, 50, 2500),
    ]
    t1 = byte_tracker.update(dummy1)
    print(f"Frame 1 Tracks: {t1}")

    dummy2 = [
        ObstacleObject("person", 0.93, [12, 11, 52, 51], 32.0, 31.0, 40, 40, 1600),
        ObstacleObject("chair", 0.80, [102, 101, 152, 151], 127.0, 126.0, 50, 50, 2500),
    ]
    t2 = byte_tracker.update(dummy2)
    print(f"Frame 2 Tracks: {t2}")

    print("ByteTracker test finished cleanly.", flush=True)
