"""
shared_state.py
---------------
All shared mutable state for the HapticGuide RTSP backend.

This module contains ONLY data structures, locks, and pure helper functions.
No I/O, no threads, no imports of cv2/numpy are performed here.

Thread safety
-------------
Every mutable value is guarded by a dedicated threading.Lock.
Locks are always acquired for the shortest possible duration (pointer swap
or scalar read/write), so they never become a throughput bottleneck.

Modules that write                       Modules that read
─────────────────────────────────────    ──────────────────────────────────
camera_stream.py  → frame_slot          routes.py          → get_stats()
camera_stream.py  → stream_stats        routes.py          → get_stats()
                                        main.py            → get_stats()
"""

import threading
import time
from typing import Optional, Any
import numpy as np


# ---------------------------------------------------------------------------
# Frame slot
# ---------------------------------------------------------------------------
# Stores the single most-recent BGR frame decoded from the RTSP stream.
# camera_stream.py overwrites this on every captured frame.
# Future AI worker will swap it to None when it starts processing.
#
# Also stores the monotonic timestamp (time.monotonic()) of when the frame
# was placed here, so consumers can calculate frame age.

class FrameSlot:
    """
    Thread-safe single-frame slot.

    Semantics: latest-wins. Any write discards the previous frame.
    Readers get the frame plus its capture timestamp in one atomic operation
    so frame-age calculations are always consistent.
    """

    def __init__(self) -> None:
        self._lock      = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._ts: float = 0.0          # time.monotonic() when frame was stored

    def put(self, frame: np.ndarray) -> None:
        """Overwrite the slot with the newest frame (non-blocking)."""
        with self._lock:
            self._frame = frame
            self._ts    = time.monotonic()

    def get(self) -> tuple[Optional[np.ndarray], float]:
        """
        Return (frame, timestamp) atomically.
        timestamp is time.monotonic() from when the frame was stored.
        Returns (None, 0.0) if no frame has arrived yet.
        """
        with self._lock:
            return self._frame, self._ts

    def get_age_ms(self) -> float:
        """
        How old is the current frame in milliseconds?
        Returns 0.0 if no frame has arrived.
        """
        with self._lock:
            if self._frame is None:
                return 0.0
            return (time.monotonic() - self._ts) * 1000.0

    def is_fresh(self, max_age_s: float = 1.0) -> bool:
        """True if a frame exists and is younger than max_age_s seconds."""
        with self._lock:
            if self._frame is None:
                return False
            return (time.monotonic() - self._ts) < max_age_s


# Module-level singleton — import this object everywhere
frame_slot = FrameSlot()


# ---------------------------------------------------------------------------
# Stream statistics
# ---------------------------------------------------------------------------
# Written by camera_stream.py, read by routes.py and the stats printer.

class StreamStats:
    """
    Thread-safe container for all RTSP stream performance metrics.

    Designed for frequent small writes (each captured frame updates fps/latency)
    and infrequent bulk reads (the stats printer and /stats endpoint).
    A single lock guards the whole struct — the critical section is trivially
    short (scalar assignments / dict copy).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Connection state
        self.connected:        bool  = False
        self.rtsp_url:         str   = ""
        self.client_ip:        str   = ""
        self.resolution:       str   = "0×0"

        # Throughput & Performance Measurements
        self.recv_fps:               float = 0.0   # Network receipt rate (FPS)
        self.decode_fps:             float = 0.0   # Image decode rate (FPS)
        self.capture_fps:            float = 0.0   # Backward compat alias for decode_fps
        self.decode_time_ms:         float = 0.0   # cv2.imdecode duration in milliseconds
        self.total_pipeline_time_ms: float = 0.0   # End-to-end socket -> decision latency
        self.jpeg_size_kb:           float = 0.0   # Size of JPEG frame in KB
        self.bytes_per_second:       float = 0.0
        self.frame_number:           int   = 0

        # Latency
        self.frame_age_ms:     float = 0.0   # age of the frame currently in slot

        # Reliability
        self.reconnect_count:  int   = 0
        self.dropped_frames:   int   = 0

        # Internal fps-window accumulators
        self._recv_count:       int   = 0
        self._decode_count:     int   = 0
        self._byte_count:      int   = 0
        self._decode_time_sum: float = 0.0
        self._window_start:    float = time.monotonic()

    def reset(self) -> None:
        """Reset all metrics to initial state for a new stream session."""
        with self._lock:
            self.connected               = False
            self.rtsp_url                = ""
            self.client_ip               = ""
            self.resolution              = "0×0"
            self.recv_fps                = 0.0
            self.decode_fps              = 0.0
            self.capture_fps             = 0.0
            self.decode_time_ms          = 0.0
            self.total_pipeline_time_ms  = 0.0
            self.jpeg_size_kb            = 0.0
            self.bytes_per_second        = 0.0
            self.frame_number            = 0
            self.frame_age_ms            = 0.0
            self.reconnect_count         = 0
            self.dropped_frames          = 0
            self._recv_count             = 0
            self._decode_count           = 0
            self._byte_count             = 0
            self._decode_time_sum        = 0.0
            self._window_start           = time.monotonic()

    # ── Setters (called from camera_stream.py, always under _lock) ───────────

    def mark_connected(self, rtsp_url: str, width: int, height: int) -> None:
        with self._lock:
            self.connected   = True
            self.rtsp_url    = rtsp_url
            if "tcp://" in rtsp_url:
                self.client_ip = rtsp_url.replace("tcp://", "").split(":")[0]
            else:
                self.client_ip = rtsp_url.split(":")[0] if ":" in rtsp_url else rtsp_url
            self.resolution  = f"{width}×{height}"
            self._recv_count        = 0
            self._decode_count      = 0
            self._byte_count        = 0
            self._decode_time_sum   = 0.0
            self._window_start      = time.monotonic()
            self.bytes_per_second   = 0.0
            self.recv_fps           = 0.0
            self.decode_fps         = 0.0
            self.capture_fps        = 0.0

    def mark_disconnected(self) -> None:
        with self._lock:
            self.connected        = False
            self.client_ip        = ""
            self.recv_fps         = 0.0
            self.decode_fps       = 0.0
            self.capture_fps      = 0.0
            self.bytes_per_second = 0.0

    def increment_reconnect(self) -> None:
        with self._lock:
            self.reconnect_count += 1

    def record_receive(self, frame_bytes: int) -> None:
        """Called once per frame header + payload received over TCP."""
        with self._lock:
            self._recv_count += 1
            self._byte_count += frame_bytes

    def record_decode(self, decode_time_ms: float, jpeg_size_bytes: int, age_ms: float) -> None:
        """
        Called once per frame decoded by cv2.imdecode.
        Updates rolling windows for FPS, throughput, decode time, and latency.
        """
        with self._lock:
            self.frame_number   += 1
            self.frame_age_ms    = age_ms
            self.jpeg_size_kb    = jpeg_size_bytes / 1024.0

            self._decode_count    += 1
            self._decode_time_sum += decode_time_ms

            now = time.monotonic()
            elapsed = now - self._window_start
            if elapsed >= 1.0:
                self.recv_fps         = self._recv_count / elapsed
                self.decode_fps       = self._decode_count / elapsed
                self.capture_fps      = self.decode_fps
                self.bytes_per_second = self._byte_count / elapsed
                if self._decode_count > 0:
                    self.decode_time_ms = self._decode_time_sum / self._decode_count

                self._recv_count      = 0
                self._decode_count    = 0
                self._byte_count      = 0
                self._decode_time_sum = 0.0
                self._window_start    = now

    def record_frame(self, age_ms: float, frame_bytes: int = 0) -> None:
        """Backward-compatible wrapper for record_decode."""
        self.record_decode(decode_time_ms=0.0, jpeg_size_bytes=frame_bytes, age_ms=age_ms)

    def record_pipeline_time(self, total_ms: float) -> None:
        """Record end-to-end socket receipt to AI decision completion latency."""
        with self._lock:
            self.total_pipeline_time_ms = total_ms

    def record_dropped(self) -> None:
        with self._lock:
            self.dropped_frames += 1

    # ── Snapshot (called from routes.py, read-only) ───────────────────────────

    def snapshot(self) -> dict:
        """
        Return a consistent, JSON-serialisable snapshot of all stats.
        """
        with self._lock:
            return {
                "connected":                self.connected,
                "rtsp_url":                 self.rtsp_url,
                "client_ip":                self.client_ip,
                "resolution":               self.resolution,
                "recv_fps":                 round(self.recv_fps, 1),
                "decode_fps":               round(self.decode_fps, 1),
                "capture_fps":              round(self.capture_fps, 1),
                "decode_time_ms":           round(self.decode_time_ms, 2),
                "total_pipeline_time_ms":   round(self.total_pipeline_time_ms, 1),
                "jpeg_size_kb":             round(self.jpeg_size_kb, 1),
                "bytes_per_second":         round(self.bytes_per_second, 1),
                "frame_number":             self.frame_number,
                "frame_age_ms":             round(self.frame_age_ms, 1),
                "reconnect_count":          self.reconnect_count,
                "dropped_frames":           self.dropped_frames,
            }


# Module-level singleton
stream_stats = StreamStats()


# ---------------------------------------------------------------------------
# Stop event
# ---------------------------------------------------------------------------
# Set by main.py shutdown hook; camera_stream.py polls it to exit cleanly.

stop_event = threading.Event()
