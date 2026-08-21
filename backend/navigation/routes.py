"""
HTTP endpoints for navigation GPS ingest.

Mounted by main.py. Isolated from obstacle /cmd handlers.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from navigation import session
from navigation.gps import (
    GpsIngestError,
    apply_gps_fault,
    apply_gps_fix,
    gps_status_payload,
    health_from_name,
    validate_coordinates,
)
from navigation.routing import calculate_route_and_update_state
from navigation.search import search_destination_and_update_state
from navigation.state import GeoPoint

router = APIRouter(prefix="/nav", tags=["navigation"])


@router.post("/gps")
async def post_gps(payload: dict) -> JSONResponse:
    """Accept a phone GPS sample and store it on the navigation session."""
    with session.get_lock():
        try:
            body = apply_gps_fix(
                session.get_state(),
                payload.get("latitude"),
                payload.get("longitude"),
                accuracy_m=payload.get("accuracy_m"),
            )
        except GpsIngestError as exc:
            apply_gps_fault(session.get_state(), exc.health, exc.message)
            return JSONResponse(
                {"ok": False, "error": exc.message, **gps_status_payload(session.get_state())},
                status_code=422,
            )
    return JSONResponse({"ok": True, **body})


@router.post("/gps/fault")
async def post_gps_fault(payload: dict) -> JSONResponse:
    """Phone reports permission denied, GPS off, or location unavailable."""
    try:
        health = health_from_name(payload.get("health") or payload.get("type"))
        detail = str(payload.get("message") or payload.get("detail") or health.value)
    except GpsIngestError as exc:
        return JSONResponse({"ok": False, "error": exc.message}, status_code=422)
    with session.get_lock():
        body = apply_gps_fault(session.get_state(), health, detail)
    return JSONResponse({"ok": True, **body})


@router.post("/search")
async def post_search(payload: dict) -> JSONResponse:
    """
    Search for nearby places in OpenStreetMap via Overpass API and update navigation state.
    """
    raw_query = payload.get("query") or payload.get("destination") or payload.get("text")
    if not isinstance(raw_query, str) or not raw_query.strip():
        with session.get_lock():
            snap = gps_status_payload(session.get_state())
        return JSONResponse(
            {"ok": False, "error": "Destination query must be a non-empty string.", **snap},
            status_code=422,
        )

    radius_m = payload.get("radius_m")
    if radius_m is not None:
        try:
            radius_m = int(radius_m)
        except (TypeError, ValueError):
            radius_m = None

    with session.get_lock():
        state = session.get_state()
        origin: Optional[GeoPoint] = None

        if payload.get("latitude") is not None and payload.get("longitude") is not None:
            try:
                lat, lon = validate_coordinates(payload.get("latitude"), payload.get("longitude"))
                origin = GeoPoint(latitude=lat, longitude=lon)
            except GpsIngestError as exc:
                return JSONResponse(
                    {"ok": False, "error": f"Invalid origin coordinates: {exc.message}", **gps_status_payload(state)},
                    status_code=422,
                )
        elif state.current_location is not None:
            origin = GeoPoint(
                latitude=state.current_location.latitude,
                longitude=state.current_location.longitude,
            )
        else:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Current GPS location is required to search for nearby destinations.",
                    **gps_status_payload(state),
                },
                status_code=422,
            )

        candidate = search_destination_and_update_state(
            state=state,
            query=raw_query,
            origin=origin,
            radius_m=radius_m,
        )

        if candidate is not None:
            return JSONResponse(
                {
                    "ok": True,
                    "destination": {
                        "name": candidate.name,
                        "latitude": candidate.location.latitude,
                        "longitude": candidate.location.longitude,
                        "distance_m": candidate.distance_m,
                        "osm_id": candidate.osm_id,
                        "osm_type": candidate.osm_type,
                        "tags": candidate.tags,
                    },
                    **gps_status_payload(state),
                }
            )
        else:
            status_code = 404 if "No matching destination" in (state.error_message or "") else 502
            return JSONResponse(
                {
                    "ok": False,
                    "error": state.error_message or "Destination search failed.",
                    **gps_status_payload(state),
                },
                status_code=status_code,
            )


@router.post("/destination")
async def post_destination(payload: dict) -> JSONResponse:
    """Alias for /nav/search."""
    return await post_search(payload)


@router.post("/route")
async def post_calculate_route(payload: Optional[dict] = None) -> JSONResponse:
    """
    Calculate route between current GPS origin and destination using OSRM.
    """
    body = payload or {}
    with session.get_lock():
        state = session.get_state()
        origin: Optional[GeoPoint] = None
        destination: Optional[GeoPoint] = None

        if body.get("origin_latitude") is not None and body.get("origin_longitude") is not None:
            try:
                lat, lon = validate_coordinates(body.get("origin_latitude"), body.get("origin_longitude"))
                origin = GeoPoint(latitude=lat, longitude=lon)
            except GpsIngestError as exc:
                return JSONResponse(
                    {"ok": False, "error": f"Invalid origin coordinates: {exc.message}", **gps_status_payload(state)},
                    status_code=422,
                )
        elif state.current_location is not None:
            origin = GeoPoint(
                latitude=state.current_location.latitude,
                longitude=state.current_location.longitude,
            )
        else:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Current GPS location is required to calculate route.",
                    **gps_status_payload(state),
                },
                status_code=422,
            )

        if body.get("destination_latitude") is not None and body.get("destination_longitude") is not None:
            try:
                d_lat, d_lon = validate_coordinates(body.get("destination_latitude"), body.get("destination_longitude"))
                destination = GeoPoint(latitude=d_lat, longitude=d_lon)
            except GpsIngestError as exc:
                return JSONResponse(
                    {"ok": False, "error": f"Invalid destination coordinates: {exc.message}", **gps_status_payload(state)},
                    status_code=422,
                )
        elif state.destination is not None:
            destination = state.destination
        else:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Destination is required to calculate route. Search destination or provide coordinates.",
                    **gps_status_payload(state),
                },
                status_code=422,
            )

        route = calculate_route_and_update_state(
            state=state,
            origin=origin,
            destination=destination,
        )

        if route is not None:
            return JSONResponse(
                {
                    "ok": True,
                    "route": {
                        "total_distance_m": route.total_distance_m,
                        "total_duration_s": route.total_duration_s,
                        "steps_count": len(route.steps),
                        "current_instruction": route.current.text if route.current else None,
                        "next_instruction": route.next.text if route.next else None,
                        "distance_to_next_m": route.distance_to_next_m,
                    },
                    **gps_status_payload(state),
                }
            )
        else:
            return JSONResponse(
                {
                    "ok": False,
                    "error": state.error_message or "Route calculation failed.",
                    **gps_status_payload(state),
                },
                status_code=502,
            )


@router.post("/calculate-route")
async def post_calculate_route_alias(payload: Optional[dict] = None) -> JSONResponse:
    """Alias for /nav/route."""
    return await post_calculate_route(payload)


@router.post("/start")
async def post_start_navigation() -> JSONResponse:
    """Start live route following on an active route."""
    with session.get_lock():
        state = session.get_state()
        if state.active_route is None:
            return JSONResponse(
                {"ok": False, "error": "No active route calculated to follow.", **gps_status_payload(state)},
                status_code=422,
            )
        if state.status is NavigationStatus.ROUTE_READY:
            state.begin_navigation()
        from navigation.follower import update_route_progress
        progress = update_route_progress(state)
        return JSONResponse({"ok": True, "progress": progress.__dict__, **gps_status_payload(state)})


@router.get("/progress")
async def get_route_progress() -> JSONResponse:
    """Retrieve current route following progress and maneuver state."""
    with session.get_lock():
        state = session.get_state()
        from navigation.follower import update_route_progress
        progress = update_route_progress(state)
        return JSONResponse({"ok": True, "progress": progress.__dict__, **gps_status_payload(state)})


@router.post("/voice")
async def post_voice_command(request: Request) -> JSONResponse:
    """
    Accept audio recording from Android microphone, transcribe via Groq STT,
    validate wake phrase ('Hello Haptic Guide'), extract destination, and execute
    Phase 3 search and Phase 4 route calculation.
    """
    content_type = request.headers.get("content-type", "")
    audio_bytes = b""
    filename = "voice_command.m4a"

    if "multipart/form-data" in content_type:
        form = await request.form()
        file_item = form.get("file") or form.get("audio")
        if file_item is not None and hasattr(file_item, "read"):
            audio_bytes = await file_item.read()
            if hasattr(file_item, "filename") and file_item.filename:
                filename = file_item.filename
    elif "application/json" in content_type:
        try:
            body = await request.json()
            if "audio_base64" in body:
                import base64
                audio_bytes = base64.b64decode(body["audio_base64"])
            filename = body.get("filename", filename)
        except Exception:
            pass
    else:
        audio_bytes = await request.body()

    if not audio_bytes or len(audio_bytes) == 0:
        with session.get_lock():
            snap = gps_status_payload(session.get_state())
        return JSONResponse(
            {"ok": False, "error": "No audio file or data supplied in request.", **snap},
            status_code=400,
        )

    with session.get_lock():
        state = session.get_state()
        from navigation.stt import process_voice_destination
        res = process_voice_destination(audio_bytes=audio_bytes, state=state, filename=filename)

        if res.ok:
            return JSONResponse(
                {
                    "ok": True,
                    "transcript": res.transcript,
                    "wake_phrase_detected": res.wake_phrase_detected,
                    "destination_query": res.destination_query,
                    "destination": {
                        "name": res.candidate.name if res.candidate else None,
                        "latitude": res.candidate.location.latitude if res.candidate else None,
                        "longitude": res.candidate.location.longitude if res.candidate else None,
                        "distance_m": res.candidate.distance_m if res.candidate else None,
                    } if res.candidate else None,
                    "route": {
                        "total_distance_m": res.route.total_distance_m,
                        "total_duration_s": res.route.total_duration_s,
                        "steps_count": len(res.route.steps),
                        "current_instruction": res.route.current.text if res.route.current else None,
                    } if res.route else None,
                    **gps_status_payload(state),
                }
            )
        else:
            status_code = 422 if not res.wake_phrase_detected else 404 if "No destination found" in (res.error or "") else 502
            return JSONResponse(
                {
                    "ok": False,
                    "transcript": res.transcript,
                    "wake_phrase_detected": res.wake_phrase_detected,
                    "destination_query": res.destination_query,
                    "error": res.error,
                    **gps_status_payload(state),
                },
                status_code=status_code,
            )


@router.post("/stt")
async def post_stt_alias(request: Request) -> JSONResponse:
    """Alias for /nav/voice."""
    return await post_voice_command(request)


@router.post("/reset")
async def post_nav_reset() -> JSONResponse:
    """Reset navigation state and active route."""
    with session.get_lock():
        state = session.get_state()
        state.reset()
        from navigation.emitter import get_emitter
        get_emitter().reset()
        return JSONResponse({"ok": True, "message": "Navigation reset to IDLE.", **gps_status_payload(state)})


@router.get("/status")
async def get_nav_status() -> JSONResponse:
    with session.get_lock():
        return JSONResponse(gps_status_payload(session.get_state()))
