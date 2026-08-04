"""
tracker.py
----------
Root wrapper module for ByteTracker.
Imports ByteTracker, TrackedObject, and track_objects from backend/tracker.py.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path if not present
backend_dir = Path(__file__).parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.tracker import ByteTracker, TrackedObject, byte_tracker, track_objects

__all__ = ["ByteTracker", "TrackedObject", "byte_tracker", "track_objects"]
