"""
HTTP endpoints for navigation GPS ingest.

Mounted by main.py. Isolated from obstacle /cmd handlers.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from navigation import session
from navigation.gps import (
    GpsIngestError,
    apply_gps_fault,
    apply_gps_fix,
    gps_status_payload,
    health_from_name,
)

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


@router.get("/status")
async def get_nav_status() -> JSONResponse:
    with session.get_lock():
        return JSONResponse(gps_status_payload(session.get_state()))
