"""
test_camera_stream.py
---------------------
Unit test for high-performance TCP CameraStream receiver.
"""

import sys
import socket
import struct
import time
from pathlib import Path
import numpy as np
import cv2
import pytest

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from camera_stream import CameraStream
from shared_state import frame_slot, stream_stats


def test_camera_stream_tcp_receipt_and_metrics():
    test_port = 9876
    stream = CameraStream(tcp_port=test_port, show_window=False)
    stream.start()

    try:
        time.sleep(0.2)

        # Create a dummy image and encode to JPEG
        test_img = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(test_img, "OPTIMIZED", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        ok, jpeg_bytes = cv2.imencode(".jpg", test_img)
        assert ok, "Failed to encode test frame to JPEG"
        jpeg_data = jpeg_bytes.tobytes()

        # Connect client socket
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", test_port))

        # Send multiple frames in rapid succession (simulating 30 FPS stream)
        length_header = struct.pack(">I", len(jpeg_data))
        packet = length_header + jpeg_data

        for _ in range(30):
            client_sock.sendall(packet)
            time.sleep(0.01)

        time.sleep(0.3)

        frame, ts = stream.get_latest_frame()
        assert frame is not None, "Frame should have been received and decoded"
        assert frame.shape == (240, 320, 3)

        snapshot = stream_stats.snapshot()
        assert snapshot["connected"] is True
        assert snapshot["resolution"] == "320×240"
        assert snapshot["frame_number"] >= 1
        assert "recv_fps" in snapshot
        assert "decode_fps" in snapshot
        assert "decode_time_ms" in snapshot
        assert "jpeg_size_kb" in snapshot
        assert snapshot["jpeg_size_kb"] > 0
        assert snapshot["frame_age_ms"] < 100.0, f"Latency too high: {snapshot['frame_age_ms']} ms"

        client_sock.close()
        time.sleep(0.3)

    finally:
        stream.stop()
