"""
Interfaces for services that will feed NavigationState later.

Phase 1 defines the shapes only. No GPS, Groq, Overpass, or OSRM clients.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from navigation.state import GeoPoint, GpsFix, PlaceCandidate, RouteSnapshot


@runtime_checkable
class LocationSource(Protocol):
    """Phone GPS adapter. Reads navigation session; must not write obstacle PWM."""

    def current_fix(self) -> Optional[GpsFix]:
        ...


@runtime_checkable
class DestinationSearchService(Protocol):
    """Future OpenStreetMap / Overpass adapter."""

    def search_nearby(self, query: str, origin: GeoPoint) -> Optional[PlaceCandidate]:
        ...


@runtime_checkable
class RoutingService(Protocol):
    """Future OSRM adapter."""

    def calculate_route(self, origin: GeoPoint, destination: GeoPoint) -> Optional[RouteSnapshot]:
        ...


@runtime_checkable
class SpeechToTextService(Protocol):
    """Future Groq STT adapter. API keys stay on the backend."""

    def transcribe(self, audio: bytes) -> str:
        ...
