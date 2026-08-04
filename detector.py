"""
detector.py
-----------
Root wrapper module for YOLODetector.
Imports YOLODetector and DetectedObject from backend/detector.py.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path if not present
backend_dir = Path(__file__).parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.detector import YOLODetector, DetectedObject

__all__ = ["YOLODetector", "DetectedObject"]
