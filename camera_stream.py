"""
camera_stream.py
----------------
TCP frame receiver for the HapticGuide Android camera client.
"""

import sys
import time
from pathlib import Path

# Add backend directory to sys.path if not present
backend_dir = Path(__file__).parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from camera_stream import CameraStream, DEFAULT_TCP_PORT, stream_stats, frame_slot

__all__ = ["CameraStream", "DEFAULT_TCP_PORT", "stream_stats", "frame_slot"]

if __name__ == "__main__":
    stream = CameraStream(tcp_port=DEFAULT_TCP_PORT, show_window=True)
    stream.start()
    try:
        while stream._running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
