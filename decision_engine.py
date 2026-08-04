"""
decision_engine.py
-------------------
Root wrapper module for DecisionEngine.
Imports DecisionEngine, decision_engine, and make_decision from backend/decision_engine.py.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path if not present
backend_dir = Path(__file__).parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.decision_engine import DecisionEngine, decision_engine, make_decision

__all__ = ["DecisionEngine", "decision_engine", "make_decision"]
