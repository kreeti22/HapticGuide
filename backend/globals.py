"""
globals.py
----------
All shared mutable state for the HapticGuide backend.

Three concerns are separated deliberately:
  1. Frame slot      — latest decoded BGR frame waiting for the AI worker.
  2. Command slot    — latest motor command produced by the AI worker.
  3. Perf counters   — rolling statistics exposed via GET /stats.

Locking strategy
----------------
* frame_lock  — threading.Lock (not asyncio) because the AI worker runs in
                a ThreadPoolExecutor.  The FastAPI coroutine acquires it only
                for a microsecond to swap the pointer; the lock is never held
                during I/O or inference.
* command_lock — same rationale; the worker writes, the route handler reads.
* All perf counter updates use a dedicated perf_lock so stats remain
  consistent under concurrent writes from the worker thread.

Nothing in this module performs I/O or computation.
"""

import threading
import time
from typing import Optional
import numpy as np

# ---------------------------------------------------------------------------
# Frame slot
# ---------------------------------------------------------------------------
# Holds the single most-recent decoded frame.  Overwritten on every upload.
# The AI worker atomically swaps this to None when it starts processing.
latest_frame: Optional[np.ndarray] = None
frame_lock = threading.Lock()

# Signals the worker that a new frame is available.
# Using threading.Event because the worker runs in a plain thread.
frame_event = threading.Event()

# ---------------------------------------------------------------------------
# Command slot
# ---------------------------------------------------------------------------
# Motor command written by the AI worker, read by GET /cmd.
# Shape is fixed so the ESP32 / Android client never sees a key mismatch.
latest_command: dict = {
    "left":  0,
    "front": 0,
    "right": 0,
    "back":  0,
}
command_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Performance counters
# ---------------------------------------------------------------------------
perf_lock = threading.Lock()

_perf: dict = {
    "camera_fps":          0.0,
    "ai_fps":              0.0,
    "yolo_fps":            0.0,
    "current_resolution":  "0x0",
    "inference_time_ms":   0.0,
    "current_rtsp_url":    "",
    "selected_imgsz":      320,
    "current_gpu":         "cpu",
}


def update_stream_status(camera_fps: float, resolution: str, rtsp_url: str) -> None:
    """Publish the latest RTSP stream metrics from the receiver."""
    with perf_lock:
        _perf["camera_fps"] = camera_fps
        _perf["current_resolution"] = resolution
        _perf["current_rtsp_url"] = rtsp_url


def update_ai_status(ai_fps: float, yolo_fps: float, inference_time_ms: float, selected_imgsz: int, current_gpu: str) -> None:
    """Publish the latest AI worker metrics."""
    with perf_lock:
        _perf["ai_fps"] = ai_fps
        _perf["yolo_fps"] = yolo_fps
        _perf["inference_time_ms"] = inference_time_ms
        _perf["selected_imgsz"] = selected_imgsz
        _perf["current_gpu"] = current_gpu


def get_api_stats() -> dict:
    """Return the read-only metrics payload exposed by FastAPI."""
    with perf_lock:
        return {
            "camera_fps": round(_perf["camera_fps"], 1),
            "ai_fps": round(_perf["ai_fps"], 1),
            "yolo_fps": round(_perf["yolo_fps"], 1),
            "current_resolution": _perf["current_resolution"],
            "inference_time_ms": round(_perf["inference_time_ms"], 1),
            "current_rtsp_url": _perf["current_rtsp_url"],
            "selected_imgsz": _perf["selected_imgsz"],
            "current_gpu": _perf["current_gpu"],
        }
