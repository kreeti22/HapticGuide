"""
object_analyzer.py
-------------------
Root wrapper module for ObjectAnalyzer.
Imports ObjectAnalyzer, AnalyzedObject, object_analyzer, analyze_objects, and PRIORITY_TABLE from backend/object_analyzer.py.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path if not present
backend_dir = Path(__file__).parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.object_analyzer import ObjectAnalyzer, AnalyzedObject, object_analyzer, analyze_objects, PRIORITY_TABLE
from backend.priority_table import PRIORITY_TABLE, DEFAULT_PRIORITY

__all__ = ["ObjectAnalyzer", "AnalyzedObject", "object_analyzer", "analyze_objects", "PRIORITY_TABLE", "DEFAULT_PRIORITY"]
