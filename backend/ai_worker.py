"""
ai_worker.py
------------
Continuous AI inference worker for the HapticGuide backend.

Pipeline Architecture
---------------------
  Latest Frame (from frame_slot)
        │
        ▼
  YOLODetector.detect()
        │
        ▼
  ObjectAnalyzer.analyze()
        │
        ▼
  ObjectFilter.filter()
        │
        ▼
  ByteTracker.update()
        │
        ▼
  RiskEstimator.estimate_risk()
        │
        ▼
  DecisionEngine.compute_motor_command() ──► globals.latest_command
        │
        ▼
  OpenCV Debug Display ("HapticGuide AI Debug") & Terminal Output

Requirements
------------
  - Continuous loop: fetch latest frame, run YOLODetector, ObjectFilter, ByteTracker, RiskEstimator, DecisionEngine.
  - Draw object IDs and risk scores on debug window.
  - Store computed motor command in globals.latest_command for FastAPI GET /cmd.
  - OpenCV debug window renders overlays ONLY on frame.copy(). Never mutates latest_frame.
"""

from __future__ import annotations

import threading
import time
from typing import Optional, List, Dict

import cv2
import numpy as np

from shared_state import frame_slot, stream_stats
from detector import YOLODetector, DetectedObject
from object_analyzer import ObjectAnalyzer, AnalyzedObject, object_analyzer
from object_filter import ObjectFilter, object_filter
from target_selector import TargetSelector, SelectedTarget, target_selector
from tracker import ByteTracker, TrackedObject, byte_tracker
from risk_estimator import RiskEstimator, RiskObject, risk_estimator
from decision_engine import DecisionEngine, decision_engine
import globals

WINDOW_NAME = "HapticGuide AI Debug"


class AIWorker:
    """
    Continuous worker thread that pulls the latest frame from frame_slot,
    runs YOLODetector inference, enriches objects via ObjectAnalyzer, filters objects via ObjectFilter,
    tracks objects via ByteTracker, assesses collision risk via RiskEstimator, computes motor commands via DecisionEngine,
    updates FPS metrics, and renders an OpenCV debug window.
    """

    def __init__(self, stream=None) -> None:
        self._stream = stream
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._show_debug_window: bool = True

        self.detector: Optional[YOLODetector] = None
        self.object_analyzer: ObjectAnalyzer = object_analyzer
        self.object_filter: ObjectFilter = object_filter
        self.target_selector: TargetSelector = target_selector
        self.tracker: ByteTracker = byte_tracker
        self.risk_estimator: RiskEstimator = risk_estimator
        self.decision_engine: DecisionEngine = decision_engine

        # Perf tracking
        self._frame_count: int = 0
        self._fps_window_start: float = 0.0
        self._ai_fps: float = 0.0
        self._yolo_ms: float = 0.0

    def start(self) -> None:
        """Start the background AI worker daemon thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._show_debug_window = True
        self._thread = threading.Thread(
            target=self._run,
            name="ai-worker",
            daemon=True,
        )
        self._thread.start()
        print("[AIWorker] Started background AI processing thread.", flush=True)

    def stop(self) -> None:
        """Signal worker thread to stop and wait for termination."""
        print("[AIWorker] Stopping...", flush=True)
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._show_debug_window:
            try:
                cv2.destroyWindow(WINDOW_NAME)
            except Exception:
                pass

        print("[AIWorker] Stopped.", flush=True)

    def _run(self) -> None:
        """Main continuous execution loop (Frame -> YOLO -> Analyzer -> Filter -> Track -> Risk -> Decision -> Display)."""
        last_frame_ts: float = 0.0

        if self.detector is None:
            self.detector = YOLODetector()

        while not self._stop_event.is_set():
            # 1. Fetch latest frame from stream or shared frame_slot
            if self._stream is not None and hasattr(self._stream, "get_latest_frame"):
                frame, ts = self._stream.get_latest_frame()
            else:
                frame, ts = frame_slot.get()

            # If no frame is available yet, display "Waiting for Camera..." image
            if frame is None:
                self._render_waiting_frame()
                time.sleep(0.01)
                continue

            # Skip if we already processed this frame
            if ts == last_frame_ts:
                self._handle_window_events()
                time.sleep(0.005)
                continue

            last_frame_ts = ts
            frame_age_ms = (time.monotonic() - ts) * 1000.0
            h, w = frame.shape[:2]

            # 2. Pipeline execution: YOLO -> Analyzer -> Filter -> Track -> Risk -> Decision
            yolo_start = time.perf_counter()
            detections: List[DetectedObject] = self.detector.detect(frame)
            analyzed_objects: List[AnalyzedObject] = self.object_analyzer.analyze(detections, img_width=w)

            # Select ONE target from all analyzed objects (largest area — Rule V1)
            selected_target: Optional[SelectedTarget] = self.target_selector.select(analyzed_objects)

            raw_count = len(self.detector.last_raw_boxes) if hasattr(self.detector, "last_raw_boxes") and self.detector.last_raw_boxes is not None else len(detections)
            conversion_count = len(detections)

            filtered_detections: List[DetectedObject] = self.object_filter.filter(detections)
            filter_count = len(filtered_detections)

            tracked_objects: List[TrackedObject] = self.tracker.update(filtered_detections)
            risk_objects: List[RiskObject] = self.risk_estimator.estimate_risk(tracked_objects, w, h)
            display_count = len(risk_objects)

            motor_command: Dict[str, int] = self.decision_engine.compute_motor_command(selected_target)
            self._yolo_ms = (time.perf_counter() - yolo_start) * 1000.0

            print("---------------------------------------", flush=True)
            print("PIPELINE STAGE COUNTS", flush=True)
            print(f"YOLO Raw:\n{raw_count}", flush=True)
            print(f"After Conversion:\n{conversion_count}", flush=True)
            print(f"After Filter:\n{filter_count}", flush=True)
            print(f"After Display:\n{display_count}", flush=True)
            print("---------------------------------------", flush=True)

            total_pipeline_ms = (time.monotonic() - ts) * 1000.0
            stream_stats.record_pipeline_time(total_pipeline_ms)

            # 3. Update FPS and performance metrics
            self._update_fps()
            globals.update_ai_status(
                ai_fps=self._ai_fps,
                yolo_fps=self._ai_fps,
                inference_time_ms=self._yolo_ms,
                selected_imgsz=self.detector.imgsz,
                current_gpu=self.detector.device,
            )

            # 4. Render OpenCV debug visualization window on frame.copy()
            if self._show_debug_window:
                self._render_debug_window(frame, frame_age_ms, analyzed_objects, motor_command, selected_target)

    def _render_waiting_frame(self) -> None:
        """Display black image with 'Waiting for Camera...' if window is active."""
        if not self._show_debug_window:
            return

        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(
            black_frame,
            "Waiting for Camera...",
            (160, 240),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        try:
            cv2.imshow(WINDOW_NAME, black_frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                cv2.destroyWindow(WINDOW_NAME)
                self._show_debug_window = False
        except Exception:
            pass

    def _handle_window_events(self) -> None:
        """Process OpenCV window events when frame hasn't changed."""
        if not self._show_debug_window:
            return

        try:
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                cv2.destroyWindow(WINDOW_NAME)
                self._show_debug_window = False
        except Exception:
            pass

    def _render_debug_window(
        self,
        frame: np.ndarray,
        frame_age_ms: float,
        analyzed_objects: List[AnalyzedObject],
        motor_command: Dict[str, int],
        selected_target: Optional[SelectedTarget] = None,
    ) -> None:
        """
        Render debug frame copy.

        Selected target  → green bounding box  (0, 255, 0)
        All other objects → blue bounding box   (255, 100, 0)
        Labels always show: Class, Priority, Area, Position.
        """
        debug_frame = frame.copy()
        h, w = frame.shape[:2]

        # Identify the selected target's bbox for O(1) lookup in the draw loop.
        # Use bbox as the identity key — it is unique per detection per frame.
        selected_bbox = selected_target.bbox if selected_target is not None else None

        # 1. Draw bounding boxes and metadata labels for each analyzed object
        for a_obj in analyzed_objects:
            x1, y1, x2, y2 = a_obj.bbox

            # Green for the selected target; blue for everything else
            is_selected = (selected_bbox is not None and a_obj.bbox == selected_bbox)
            color       = (0, 255, 0) if is_selected else (255, 100, 0)

            cv2.rectangle(debug_frame, (x1, y1), (x2, y2), color, 2)

            labels = [
                f"{a_obj.class_name.capitalize()}",
                f"P={a_obj.priority}",
                f"Area={a_obj.area}",
                f"{a_obj.position}",
            ]

            y_text = max(y1 - 5, 15)
            for line in reversed(labels):
                (tw, th), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                cv2.rectangle(
                    debug_frame,
                    (x1, max(y_text - th - 2, 0)),
                    (x1 + tw + 4, max(y_text + 2, th + 2)),
                    (0, 0, 0),
                    cv2.FILLED,
                )
                cv2.putText(
                    debug_frame,
                    line,
                    (x1 + 2, max(y_text - 1, th)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (0, 255, 255) if is_selected else (180, 180, 255),
                    1,
                    cv2.LINE_AA,
                )
                y_text -= (th + 6)

        # 2. Draw top-left metrics overlay
        active_motors = [f"{k[0].upper()}:{v}" for k, v in motor_command.items() if v > 0]
        cmd_summary   = ", ".join(active_motors) if active_motors else "OFF"
        target_str    = (
            f"{selected_target.class_name.capitalize()} (Area={selected_target.area})"
            if selected_target else "None"
        )

        overlay_lines = [
            f"AI FPS:   {self._ai_fps:.1f}",
            f"YOLO ms:  {self._yolo_ms:.1f}",
            f"Objects:  {len(analyzed_objects)}",
            f"Target:   {target_str}",
            f"Motor:    {cmd_summary}",
            f"Age:      {frame_age_ms:.1f} ms",
            f"Res:      {w}x{h}",
        ]

        y_pos = 25
        for line in overlay_lines:
            cv2.putText(debug_frame, line, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(debug_frame, line, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
            y_pos += 25

        try:
            cv2.imshow(WINDOW_NAME, debug_frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                cv2.destroyWindow(WINDOW_NAME)
                self._show_debug_window = False
        except Exception:
            pass

    def _update_fps(self) -> None:
        now = time.perf_counter()
        if self._fps_window_start == 0.0:
            self._fps_window_start = now
            return

        self._frame_count += 1
        elapsed = now - self._fps_window_start
        if elapsed >= 1.0:
            self._ai_fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_window_start = now


# Singleton instance
ai_worker = AIWorker()


def start_ai_worker() -> None:
    ai_worker.start()


def stop_ai_worker() -> None:
    ai_worker.stop()


if __name__ == "__main__":
    print("Starting AIWorker standalone test...", flush=True)
    # Feed dummy frame into frame_slot for testing
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(dummy_frame, "AI TEST", (100, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    frame_slot.put(dummy_frame)

    start_ai_worker()
    time.sleep(2.0)
    stop_ai_worker()

