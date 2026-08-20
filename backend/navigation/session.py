"""
Process-wide navigation session.

GPS ingest and future OSM/OSRM/Groq adapters share this instance.
It never writes obstacle PWM (globals.latest_command).
"""

from __future__ import annotations

import threading

from navigation.state import NavigationState

_lock = threading.Lock()
_state = NavigationState()


def get_state() -> NavigationState:
    return _state


def get_lock() -> threading.Lock:
    return _lock


def reset_session() -> NavigationState:
    """Replace the session. Tests only."""
    global _state
    with _lock:
        _state = NavigationState()
        return _state
