"""
object_filter.py
----------------
Root wrapper module for ObjectFilter.
Imports ObjectFilter, ObstacleObject, and filter_objects from backend/object_filter.py.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path if not present
backend_dir = Path(__file__).parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.object_filter import ObjectFilter, ObstacleObject, object_filter, filter_objects

__all__ = ["ObjectFilter", "ObstacleObject", "object_filter", "filter_objects"]
