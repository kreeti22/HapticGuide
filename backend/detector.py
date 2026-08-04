"""
detector.py
-----------
YOLOv8 Object Detector for HapticGuide.

Responsibilities:
  - Load YOLO model once at initialization.
  - Run GPU/FP16 accelerated inference on raw RGB/BGR frames.
  - Convert raw YOLO outputs into custom DetectedObject instances.
  - Log YOLO performance metrics every second.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

import numpy as np
import torch
from ultralytics import YOLO


@dataclass
class DetectedObject:
    """Custom structured representation of a single YOLO object detection."""
    class_name: str
    confidence: float
    bbox: List[int]       # [x1, y1, x2, y2] in pixel coordinates
    center_x: float       # Bounding box center X coordinate
    center_y: float       # Bounding box center Y coordinate
    width: int            # Bounding box width
    height: int           # Bounding box height
    area: int             # Bounding box area (width * height)

    def __repr__(self) -> str:
        pct = int(round(self.confidence * 100))
        return (
            f"DetectedObject({self.class_name} {pct}%, "
            f"bbox={self.bbox}, center=({self.center_x:.1f}, {self.center_y:.1f}), "
            f"size={self.width}x{self.height}, area={self.area})"
        )


class YOLODetector:
    """
    YOLOv8 object detector for frame-by-frame inference.
    Loads model once during __init__, uses CUDA/FP16 if available,
    and returns a list of custom DetectedObject instances.
    """

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.25,
        imgsz: int = 320,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.imgsz = imgsz

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.use_fp16 = torch.cuda.is_available()

        print(
            f"[YOLODetector] Initializing model '{model_path}' "
            f"on device '{self.device}' (FP16={self.use_fp16})...",
            flush=True,
        )
        self.model = YOLO(model_path)
        if torch.cuda.is_available():
            self.model.to(self.device)
            if self.use_fp16:
                self.model.model.half()

        # Print model metadata
        print("========================================", flush=True)
        print("YOLO MODEL INFORMATION", flush=True)
        print(f"Model:    {model_path}", flush=True)
        print(f"Type:     {type(self.model.model).__name__}", flush=True)
        print(f"Task:     {getattr(self.model, 'task', 'detect')}", flush=True)
        print(f"Classes:  {len(self.model.names)}", flush=True)
        print("Class Dictionary:", flush=True)
        print(self.model.names, flush=True)
        print("========================================", flush=True)

        # Performance & debug tracking
        self._frame_count: int = 0
        self._fps_window_start: float = 0.0
        self._yolo_fps: float = 0.0
        self._last_inference_ms: float = 0.0
        self._last_print_time: float = 0.0

    def detect(self, frame: np.ndarray) -> List[DetectedObject]:
        """
        Run object detection on an RGB/BGR numpy frame.

        Parameters
        ----------
        frame : np.ndarray
            Input image array of shape (H, W, 3).

        Returns
        -------
        List[DetectedObject]
            List of structured detections.
        """
        if frame is None or frame.size == 0:
            return []

        start_time = time.perf_counter()

        # Run model inference (reuse loaded model)
        results = self.model(
            frame,
            imgsz=self.imgsz,
            half=self.use_fp16,
            stream=False,
            verbose=False,
        )

        self._last_inference_ms = (time.perf_counter() - start_time) * 1000.0

        detections: List[DetectedObject] = []
        boxes = results[0].boxes
        self.last_raw_boxes = boxes

        # Immediately print EVERY raw detection returned by the model before any filtering
        print("---------------------------------------", flush=True)
        print("RAW YOLO OUTPUT", flush=True)
        if boxes is not None and len(boxes) > 0:
            for box in boxes:
                cls_id = int(box.cls[0])
                class_name = str(self.model.names[cls_id])
                conf = float(box.conf[0])
                xyxy = [int(v) for v in box.xyxy[0].tolist()]
                print(f"Class ID: {cls_id}", flush=True)
                print(f"Class: {class_name}", flush=True)
                print(f"Confidence: {conf:.2f}", flush=True)
                print(f"Bounding Box: {xyxy}", flush=True)
                print("", flush=True)
        else:
            print("No raw detections found", flush=True)
        print("---------------------------------------", flush=True)

        if boxes is not None and len(boxes) > 0:
            for box in boxes:
                conf = float(box.conf[0])
                if conf < self.confidence_threshold:
                    continue

                cls_id = int(box.cls[0])
                class_name = str(self.model.names[cls_id])
                xyxy = box.xyxy[0].tolist()

                x1, y1, x2, y2 = int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])
                w = max(0, x2 - x1)
                h = max(0, y2 - y1)
                cx = x1 + w / 2.0
                cy = y1 + h / 2.0
                area = w * h

                detections.append(
                    DetectedObject(
                        class_name=class_name,
                        confidence=round(conf, 4),
                        bbox=[x1, y1, x2, y2],
                        center_x=cx,
                        center_y=cy,
                        width=w,
                        height=h,
                        area=area,
                    )
                )

        # Performance statistics calculation
        self._update_fps()

        # Debug print every 1 second
        self._print_debug_info(detections)

        return detections

    def _update_fps(self) -> None:
        now = time.perf_counter()
        if self._fps_window_start == 0.0:
            self._fps_window_start = now
            return

        self._frame_count += 1
        elapsed = now - self._fps_window_start
        if elapsed >= 1.0:
            self._yolo_fps = self._frame_count / elapsed
            self._frame_count = 0
            self._fps_window_start = now

    def _print_debug_info(self, detections: List[DetectedObject]) -> None:
        now = time.perf_counter()
        if now - self._last_print_time < 1.0:
            return

        self._last_print_time = now

        class_counts = {}
        for obj in detections:
            cls = obj.class_name.capitalize()
            class_counts[cls] = class_counts.get(cls, 0) + 1

        classes_str = ", ".join([f"{cls} ({cnt})" for cls, cnt in class_counts.items()]) if class_counts else "None"

        print("========================================", flush=True)
        print(f"Total Objects: {len(detections)}", flush=True)
        print(f"Detected Classes: {classes_str}", flush=True)
        print(f"Objects Per Frame: {len(detections):.1f}", flush=True)
        print("========================================", flush=True)


if __name__ == "__main__":
    print("Testing YOLODetector standalone...", flush=True)
    import cv2

    detector = YOLODetector()
    dummy = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(dummy, "Detector Test", (100, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    for i in range(10):
        objs = detector.detect(dummy)
        time.sleep(0.1)

    print("YOLODetector test finished cleanly.", flush=True)
