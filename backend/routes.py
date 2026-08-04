"""
routes.py
---------
FastAPI HTTP endpoints for the HapticGuide backend.

FastAPI is strictly a read-only telemetry and state-reporting layer.
FastAPI NEVER receives, processes, or encodes video frames.

Endpoints
---------
GET /cmd    — returns the latest motor command computed by the AI worker.
GET /stats  — returns backend performance metrics and client connection telemetry.
GET /health — liveness probe for monitoring tools / ESP32.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from shared_state import stream_stats, frame_slot
import globals

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /cmd
# ---------------------------------------------------------------------------

@router.get("/cmd", response_class=JSONResponse)
async def get_cmd() -> JSONResponse:
    """
    Return the latest motor command computed by the background AI worker.

    Response shape
    --------------
    {
        "left":  int,
        "front": int,
        "right": int,
        "back":  int
    }
    """
    with globals.command_lock:
        return JSONResponse(dict(globals.latest_command))


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------

@router.get("/stats", response_class=JSONResponse)
async def get_stats() -> JSONResponse:
    """
    Return full backend performance metrics and client connection state.

    Response shape
    --------------
    {
        "camera_fps":         float,
        "recv_fps":           float,
        "ai_fps":             float,
        "frame_age_ms":       float,
        "yolo_time_ms":       float,
        "current_resolution": str,
        "client_ip":          str,
        "connected":          bool
    }
    """
    s = stream_stats.snapshot()
    ai_s = globals.get_api_stats()

    return JSONResponse({
        "camera_fps":         round(s.get("decode_fps", 0.0), 1),
        "recv_fps":           round(s.get("recv_fps", 0.0), 1),
        "ai_fps":             round(ai_s.get("ai_fps", 0.0), 1),
        "frame_age_ms":       round(frame_slot.get_age_ms(), 1),
        "yolo_time_ms":       round(ai_s.get("inference_time_ms", 0.0), 1),
        "current_resolution": s.get("resolution", "0×0"),
        "client_ip":          s.get("client_ip", ""),
        "connected":          s.get("connected", False),
    })


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@router.get("/health", response_class=JSONResponse)
async def get_health() -> JSONResponse:
    """
    Liveness probe.

    Response shape
    --------------
    {
        "status":    "ok",
        "connected": bool
    }
    """
    s = stream_stats.snapshot()
    return JSONResponse({
        "status":    "ok",
        "connected": s.get("connected", False),
    })
