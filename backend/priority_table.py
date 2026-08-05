"""
priority_table.py
-----------------
Obstacle priority scores for the HapticGuide navigation system.

These values are used exclusively by ObjectAnalyzer to enrich
DetectedObject instances with a priority score. No filtering,
ranking, or motor control happens here.

Scale
-----
  10 = highest danger  (human in path)
   0 = unknown class   (no priority assigned)

To add a new class, insert it here. object_analyzer.py will pick
it up automatically on next startup — no other file needs changing.
"""

from typing import Dict

PRIORITY_TABLE: Dict[str, int] = {
    # People
    "person":           10,

    # Two-wheeled vehicles
    "bicycle":           9,
    "motorcycle":        9,

    # Four-wheeled vehicles
    "car":               8,
    "bus":               8,
    "truck":             8,

    # Indoor furniture / obstacles
    "chair":             7,
    "table":             6,
    "dining table":      6,

    # Outdoor / street fixtures
    "bench":             5,
    "traffic light":     4,
    "stop sign":         4,
    "fire hydrant":      4,
    "door":              4,

    # Ground-level clutter
    "trash can":         4,
    "waste container":   4,
    "garbage can":       4,
    "bin":               4,

    # Carried objects (lower risk — person already captured)
    "backpack":          2,
    "suitcase":          2,

    # Small objects
    "bottle":            1,
    "cup":               1,
}

# Any class not listed above receives this default score.
DEFAULT_PRIORITY: int = 0
