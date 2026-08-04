"""
test_ai_worker.py
-----------------
Unit test for AIWorker lifecycle and command updating.
"""

import sys
import time
from pathlib import Path
import numpy as np
import cv2
import pytest

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from shared_state import frame_slot
from ai_worker import AIWorker
import globals


def test_ai_worker_lifecycle_and_command_update():
    worker = AIWorker()
    worker.start()

    try:
        # Create a test frame and put it into frame_slot
        test_img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(test_img, "OBSTACLE TEST", (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        frame_slot.put(test_img)

        # Allow worker thread to process the frame
        time.sleep(0.5)

        with globals.command_lock:
            cmd = dict(globals.latest_command)

        # Command keys must match motor axis shape
        assert "left" in cmd
        assert "front" in cmd
        assert "right" in cmd
        assert "back" in cmd

    finally:
        worker.stop()
