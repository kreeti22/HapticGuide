"""
search.py
---------
OpenStreetMap / Overpass destination search service (Phase 3).

Searches nearby OpenStreetMap data using the public Overpass API,
finds matching places (such as "nearest KFC", "coffee shop", "hospital"),
calculates geodesic distance to each result, and selects the nearest match.

Isolated inside the navigation package. Does not touch obstacle detection,
ESP32 communication, camera/TCP streaming, or OSRM routing.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from navigation.interfaces import DestinationSearchService
from navigation.state import GeoPoint, NavigationState, NavigationStatus, PlaceCandidate

logger = logging.getLogger(__name__)

DEFAULT_OVERPASS_URL: str = "https://overpass-api.de/api/interpreter"
DEFAULT_SEARCH_RADIUS_M: int = 5000
DEFAULT_TIMEOUT_S: float = 10.0
USER_AGENT: str = "HapticGuide/1.0 (Wearable Haptic Navigation)"

# Common category keywords mapped to OSM key-value pairs
CATEGORY_TAG_FILTERS: Dict[str, List[Tuple[str, str]]] = {
    "coffee shop": [("amenity", "cafe"), ("shop", "coffee")],
    "coffee": [("amenity", "cafe"), ("shop", "coffee")],
    "cafe": [("amenity", "cafe")],
    "hospital": [("amenity", "hospital"), ("amenity", "clinic")],
    "clinic": [("amenity", "clinic"), ("amenity", "hospital")],
    "pharmacy": [("amenity", "pharmacy"), ("shop", "chemist")],
    "chemist": [("amenity", "pharmacy"), ("shop", "chemist")],
    "drugstore": [("amenity", "pharmacy"), ("shop", "chemist")],
    "restaurant": [("amenity", "restaurant")],
    "fast food": [("amenity", "fast_food")],
    "supermarket": [("shop", "supermarket")],
    "grocery": [("shop", "supermarket"), ("shop", "convenience"), ("shop", "grocery")],
    "grocery store": [("shop", "supermarket"), ("shop", "convenience"), ("shop", "grocery")],
    "gas station": [("amenity", "fuel")],
    "petrol pump": [("amenity", "fuel")],
    "fuel": [("amenity", "fuel")],
    "atm": [("amenity", "atm"), ("amenity", "bank")],
    "bank": [("amenity", "bank")],
    "toilets": [("amenity", "toilets")],
    "restroom": [("amenity", "toilets")],
    "police": [("amenity", "police")],
    "police station": [("amenity", "police")],
}

_PREFIX_PATTERNS: Sequence[re.Pattern] = (
    re.compile(r"^(?:find\s+)?(?:the\s+)?(?:nearest|closest|nearby)\s+", re.IGNORECASE),
    re.compile(r"^(?:take\s+me\s+to\s+(?:the\s+)?(?:nearest|closest|nearby)\s+)", re.IGNORECASE),
    re.compile(r"^(?:take\s+me\s+to\s+(?:the\s+)?)", re.IGNORECASE),
    re.compile(r"^(?:navigate\s+to\s+(?:the\s+)?(?:nearest|closest|nearby)\s+)", re.IGNORECASE),
    re.compile(r"^(?:navigate\s+to\s+(?:the\s+)?)", re.IGNORECASE),
    re.compile(r"^(?:go\s+to\s+(?:the\s+)?(?:nearest|closest|nearby)\s+)", re.IGNORECASE),
    re.compile(r"^(?:go\s+to\s+(?:the\s+)?)", re.IGNORECASE),
    re.compile(r"^(?:search\s+for\s+(?:the\s+)?(?:nearest|closest|nearby)\s+)", re.IGNORECASE),
    re.compile(r"^(?:search\s+for\s+(?:the\s+)?)", re.IGNORECASE),
)

_SUFFIX_PATTERNS: Sequence[re.Pattern] = (
    re.compile(r"\s+(?:near\s+me|nearby|close\s+to\s+me)$", re.IGNORECASE),
)


class DestinationSearchError(Exception):
    """Raised when an Overpass search fails due to network, service, or parsing errors."""


def clean_destination_query(query: str) -> str:
    """
    Extract the core destination target or category from natural language queries.

    Examples:
        "nearest KFC" -> "KFC"
        "take me to the nearest hospital" -> "hospital"
        "coffee shop near me" -> "coffee shop"
    """
    if not isinstance(query, str):
        return ""
    text = query.strip()
    if not text:
        return ""

    for pat in _PREFIX_PATTERNS:
        match = pat.match(text)
        if match:
            text = text[match.end():].strip()
            break

    for pat in _SUFFIX_PATTERNS:
        match = pat.search(text)
        if match:
            text = text[:match.start()].strip()
            break

    return text if text else query.strip()


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in meters using Haversine formula."""
    r_earth = 6371000.0  # Mean radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r_earth * c


def build_overpass_query(
    clean_query: str,
    origin: GeoPoint,
    radius_m: int = DEFAULT_SEARCH_RADIUS_M,
    timeout_s: int = 10,
) -> str:
    """
    Build an Overpass QL query string searching nodes and ways within radius_m of origin.
    """
    lat = origin.latitude
    lon = origin.longitude
    around = f"(around:{int(radius_m)},{lat:.6f},{lon:.6f})"

    # Sanitize regex pattern for name search
    escaped_name = re.escape(clean_query).replace('"', r'\"')

    clauses: List[str] = [
        f'node["name"~"{escaped_name}",i]{around};',
        f'way["name"~"{escaped_name}",i]{around};',
        f'node["brand"~"{escaped_name}",i]{around};',
        f'way["brand"~"{escaped_name}",i]{around};',
    ]

    key = clean_query.lower()
    if key in CATEGORY_TAG_FILTERS:
        for tag_k, tag_v in CATEGORY_TAG_FILTERS[key]:
            clauses.append(f'node["{tag_k}"="{tag_v}"]{around};')
            clauses.append(f'way["{tag_k}"="{tag_v}"]{around};')

    body = "\n  ".join(clauses)
    return f"[out:json][timeout:{int(timeout_s)}];\n(\n  {body}\n);\nout center tags;"


def parse_overpass_response(
    data: Dict[str, object],
    origin: GeoPoint,
    fallback_name: str = "",
) -> List[PlaceCandidate]:
    """
    Parse Overpass JSON data, extract node and way center coordinates,
    compute Haversine distance, and return candidates sorted by distance ascending.
    """
    elements = data.get("elements")
    if not isinstance(elements, list):
        return []

    candidates: List[PlaceCandidate] = []
    seen_ids: set = set()

    for elem in elements:
        if not isinstance(elem, dict):
            continue

        elem_id = (elem.get("type"), elem.get("id"))
        if elem_id in seen_ids:
            continue
        seen_ids.add(elem_id)

        lat: Optional[float] = None
        lon: Optional[float] = None

        if "lat" in elem and "lon" in elem:
            try:
                lat = float(elem["lat"])
                lon = float(elem["lon"])
            except (TypeError, ValueError):
                pass

        if (lat is None or lon is None) and isinstance(elem.get("center"), dict):
            center = elem["center"]
            try:
                lat = float(center.get("lat"))
                lon = float(center.get("lon"))
            except (TypeError, ValueError):
                pass

        if lat is None or lon is None or not math.isfinite(lat) or not math.isfinite(lon):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        tags = elem.get("tags") if isinstance(elem.get("tags"), dict) else {}
        name = (
            tags.get("name")
            or tags.get("brand")
            or tags.get("operator")
            or tags.get("amenity")
            or fallback_name
            or "Destination"
        )

        dist = haversine_distance_m(origin.latitude, origin.longitude, lat, lon)
        candidates.append(
            PlaceCandidate(
                name=str(name),
                location=GeoPoint(latitude=lat, longitude=lon),
                distance_m=round(dist, 1),
                osm_id=elem.get("id"),
                osm_type=elem.get("type"),
                tags={str(k): str(v) for k, v in tags.items()},
            )
        )

    candidates.sort(key=lambda c: (c.distance_m if c.distance_m is not None else float("inf")))
    return candidates


class OverpassSearchService(DestinationSearchService):
    """
    DestinationSearchService backed by public OpenStreetMap / Overpass API.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        default_radius_m: int = DEFAULT_SEARCH_RADIUS_M,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        user_agent: str = USER_AGENT,
        http_requester: Optional[Callable[[str, str, float], str]] = None,
    ) -> None:
        self.endpoint = endpoint or os.environ.get("OVERPASS_URL", DEFAULT_OVERPASS_URL)
        self.default_radius_m = default_radius_m
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        self._http_requester = http_requester or self._default_http_post

    def _default_http_post(self, url: str, query_ql: str, timeout_s: float) -> str:
        data = urllib.parse.urlencode({"data": query_ql}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            return response.read().decode("utf-8", errors="replace")

    def search_all_nearby(
        self,
        query: str,
        origin: GeoPoint,
        radius_m: Optional[int] = None,
    ) -> List[PlaceCandidate]:
        """
        Query Overpass for all matching places within radius_m and return sorted list.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query string must be non-empty.")
        if not isinstance(origin, GeoPoint):
            raise ValueError("Origin must be a GeoPoint instance.")
        if not (-90.0 <= origin.latitude <= 90.0 and -180.0 <= origin.longitude <= 180.0):
            raise ValueError(f"Origin coordinates out of range: {origin}")

        clean = clean_destination_query(query)
        if not clean:
            raise ValueError("Query string contains no searchable keywords.")

        radius = radius_m if radius_m is not None and radius_m > 0 else self.default_radius_m
        overpass_ql = build_overpass_query(
            clean_query=clean,
            origin=origin,
            radius_m=radius,
            timeout_s=int(self.timeout_s),
        )

        try:
            raw_response = self._http_requester(self.endpoint, overpass_ql, self.timeout_s)
        except urllib.error.HTTPError as exc:
            logger.warning("Overpass HTTP error %d: %s", exc.code, exc.reason)
            raise DestinationSearchError(f"Overpass service error (HTTP {exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("Overpass connection failure: %s", exc)
            raise DestinationSearchError(f"Overpass network failure: {exc}") from exc
        except Exception as exc:
            logger.warning("Overpass search error: %s", exc)
            raise DestinationSearchError(f"Overpass request failed: {exc}") from exc

        try:
            parsed_json = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Malformed Overpass response JSON: %s", exc)
            raise DestinationSearchError("Malformed response from Overpass service.") from exc

        if not isinstance(parsed_json, dict):
            raise DestinationSearchError("Unexpected response structure from Overpass service.")

        return parse_overpass_response(parsed_json, origin, fallback_name=clean)

    def search_nearby(
        self,
        query: str,
        origin: GeoPoint,
        radius_m: Optional[int] = None,
    ) -> Optional[PlaceCandidate]:
        """
        Search for nearest matching place. Returns nearest PlaceCandidate or None.
        """
        candidates = self.search_all_nearby(query, origin, radius_m=radius_m)
        return candidates[0] if candidates else None


def search_destination_and_update_state(
    state: NavigationState,
    query: str,
    origin: Optional[GeoPoint] = None,
    service: Optional[DestinationSearchService] = None,
    radius_m: Optional[int] = None,
) -> Optional[PlaceCandidate]:
    """
    Orchestrate full destination search and update NavigationState.

    Transitions state to SEARCHING_DESTINATION, runs search, and transitions
    to DESTINATION_FOUND on success or ERROR on failure.
    """
    if origin is None:
        if state.current_location is None:
            state.fail("Current GPS location unavailable for destination search.")
            return None
        origin = GeoPoint(
            latitude=state.current_location.latitude,
            longitude=state.current_location.longitude,
        )

    clean_query = query.strip()
    if not clean_query:
        state.fail("Destination query must be non-empty.")
        return None

    state.set_destination_query(clean_query)
    state.begin_search()

    search_svc = service or OverpassSearchService()

    try:
        candidate = search_svc.search_nearby(clean_query, origin, radius_m=radius_m)
    except Exception as exc:
        state.fail(f"Destination search failed: {exc}")
        return None

    if candidate is None:
        state.fail(f"No matching destination found for {clean_query!r}.")
        return None

    state.set_destination(candidate)
    return candidate
