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
GET /live   — real-time haptic belt visual dashboard.
"""

import base64
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from shared_state import stream_stats, frame_slot
import globals


router = APIRouter()

# Jinja2 Templates Engine Configuration
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# GET /cmd
# ---------------------------------------------------------------------------

@router.get("/cmd", response_class=JSONResponse)
async def get_cmd() -> JSONResponse:
    """Return the latest motor command computed by the background AI worker."""
    with globals.command_lock:
        return JSONResponse(dict(globals.latest_command))


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------

@router.get("/stats", response_class=JSONResponse)
async def get_stats() -> JSONResponse:
    """Return backend performance metrics, client connection state, target, and command."""
    s = stream_stats.snapshot()
    ai_s = globals.get_api_stats()

    with globals.command_lock:
        cmd = dict(globals.latest_command)

    target = getattr(globals, "latest_target", None)
    if target is None:
        active_pos = [k.upper() if k != "front" else "CENTER" for k, v in cmd.items() if v > 0]
        current_target = active_pos[0] if active_pos else None
    else:
        current_target = target

    frame_age = round(frame_slot.get_age_ms(), 1)

    return JSONResponse({
        "camera_fps":         round(s.get("decode_fps", 0.0), 1),
        "yolo_fps":           round(ai_s.get("yolo_fps", 0.0), 1),
        "current_target":     current_target,
        "current_command":    cmd,
        "frame_age":          frame_age,
        "frame_age_ms":       frame_age,
        "recv_fps":           round(s.get("recv_fps", 0.0), 1),
        "ai_fps":             round(ai_s.get("ai_fps", 0.0), 1),
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
    """Liveness probe."""
    s = stream_stats.snapshot()
    return JSONResponse({
        "status":    "ok",
        "connected": s.get("connected", False),
    })


# ---------------------------------------------------------------------------
# SVG Asset Loaders for Dashboard
# Loads SVG assets directly from ref_img/ directory
# ---------------------------------------------------------------------------

def _load_svg_asset(filename: str) -> str:
    """Read an SVG file from the ref_img directory."""
    ref_dir = Path(__file__).parent.parent / "ref_img"
    svg_path = ref_dir / filename
    if svg_path.exists():
        return svg_path.read_text(encoding="utf-8")
    return ""


def _get_phone_svg() -> str:
    raw = _load_svg_asset("Phone.svg")
    if not raw:
        return ""
    # Make background transparent so it floats seamlessly on dark page
    raw = raw.replace('fill="#0d0e10"', 'fill="none"')
    
    # Premium Physical Smartphone Material & Lighting Gradients matching ref_img/3.png
    flash_defs = """
    <!-- LAYER 1: Core Hotspot Spot -->
    <radialGradient id="flashLayer1Core" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="45%" stop-color="#ffffff"/>
      <stop offset="80%" stop-color="#fff8e1" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="#ffe082" stop-opacity="0"/>
    </radialGradient>

    <!-- LAYER 2: Warm White Circular Bloom -->
    <radialGradient id="flashLayer2Bloom" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#fffdf5" stop-opacity="0.92"/>
      <stop offset="35%" stop-color="#ffe082" stop-opacity="0.55"/>
      <stop offset="70%" stop-color="#ffb74d" stop-opacity="0.2"/>
      <stop offset="100%" stop-color="#ff9800" stop-opacity="0"/>
    </radialGradient>

    <!-- LAYER 3: Volumetric Forward Light Scattering Falloff -->
    <radialGradient id="flashLayer3Volumetric" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.65"/>
      <stop offset="30%" stop-color="#ffe082" stop-opacity="0.32"/>
      <stop offset="65%" stop-color="#ffa726" stop-opacity="0.12"/>
      <stop offset="100%" stop-color="#fb8c00" stop-opacity="0"/>
    </radialGradient>

    <!-- LAYER 4: Atmospheric Scattering Halo -->
    <radialGradient id="flashLayer4Atmosphere" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#fff8e1" stop-opacity="0.28"/>
      <stop offset="50%" stop-color="#ffe082" stop-opacity="0.09"/>
      <stop offset="100%" stop-color="#ffb74d" stop-opacity="0"/>
    </radialGradient>

    <!-- Physical Glass Back Reflective Glare Overlay -->
    <linearGradient id="glassReflectionGlare" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.25"/>
      <stop offset="28%" stop-color="#ffffff" stop-opacity="0.08"/>
      <stop offset="60%" stop-color="#ffffff" stop-opacity="0.02"/>
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>

    <!-- Metallic Frame Highlight Gradient -->
    <linearGradient id="phoneFrameMetallic" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.3"/>
      <stop offset="30%" stop-color="#8a8a86" stop-opacity="0.15"/>
      <stop offset="70%" stop-color="#2a2a28" stop-opacity="0.05"/>
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0.2"/>
    </linearGradient>

    <filter id="bloomGlow" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="10" result="blur1"/>
      <feGaussianBlur stdDeviation="20" result="blur2"/>
      <feMerge>
        <feMergeNode in="blur2"/>
        <feMergeNode in="blur1"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>

    <filter id="outerVolumetricBlur" x="-150%" y="-150%" width="400%" height="400%">
      <feGaussianBlur stdDeviation="35"/>
    </filter>
    """

    flash_elements = """
    <!-- Premium Smartphone Glass & Atmospheric Flash Assembly -->
    <g transform="translate(100, 100)" class="flashlight-forward-group">
      
      <!-- Metallic Frame Edge Highlight -->
      <rect x="0" y="0" width="800" height="300" rx="40" fill="none" stroke="url(#phoneFrameMetallic)" stroke-width="2.5" opacity="0.8"/>

      <!-- Realistic Glass Back Glare Overlay -->
      <path d="M 4 4 H 796 V 296 H 4 Z" fill="url(#glassReflectionGlare)" clip-path="url(#phoneClip)" opacity="0.85" style="mix-blend-mode: screen;"/>

      <!-- LAYER 4: Atmospheric Scattering Halo -->
      <circle cx="695" cy="122" r="260" fill="url(#flashLayer4Atmosphere)" filter="url(#outerVolumetricBlur)" style="mix-blend-mode: screen;"/>

      <!-- LAYER 3: Volumetric Forward Beam extending toward viewer -->
      <circle cx="695" cy="122" r="140" fill="url(#flashLayer3Volumetric)" filter="url(#bloomGlow)" opacity="0.8" style="mix-blend-mode: screen;"/>

      <!-- LAYER 2: Warm White Circular Bloom around flash -->
      <circle cx="695" cy="122" r="48" fill="url(#flashLayer2Bloom)" filter="url(#bloomGlow)" opacity="0.9" style="mix-blend-mode: screen;"/>

      <!-- Concentric Forward Lens Flare Rings -->
      <circle cx="695" cy="122" r="24" fill="none" stroke="#fff8e1" stroke-width="1.5" opacity="0.4"/>

      <!-- LAYER 1: Small Extremely Bright White Center -->
      <circle cx="695" cy="122" r="14" fill="url(#flashLayer1Core)" filter="url(#bloomGlow)"/>
      <circle cx="695" cy="122" r="6" fill="#ffffff"/>
    </g>
    """

    raw = raw.replace("</defs>", flash_defs + "\n</defs>")
    raw = raw.replace("</svg>", flash_elements + "\n</svg>")
    return raw


def _get_belt_svg() -> str:
    raw = _load_svg_asset("belt.svg")
    if not raw:
        return ""

    # Remove L-shaped buckle pin & pin circle (preserving embedded native HG logo)
    pin_target = """    <!-- Buckle pin -->
    <path
      d="
        M600 246
        L600 291
        Q600 300 609 300
        H656
      "
      fill="none"
      stroke="#c6c6c2"
      stroke-width="10"
      stroke-linecap="round"
    />

    <circle
      cx="655"
      cy="300"
      r="5"
      fill="#eeeeea"
    />"""
    raw = raw.replace(pin_target, "")

    # Premium Fabric & Metallic Buckle Definitions (No duplicate HG text added)
    texture_defs = """
    <!-- Premium Woven Technical Textile Pattern -->
    <pattern id="fabricWeavePattern" width="8" height="8" patternUnits="userSpaceOnUse">
      <rect width="8" height="8" fill="#d2d2ce"/>
      <path d="M 0 4 L 8 4 M 4 0 L 4 8" stroke="#a4a4a0" stroke-width="0.7" opacity="0.45"/>
    </pattern>

    <!-- Warm Flash Reflection Overlay on Right Belt Strap -->
    <radialGradient id="flashStrapReflect" cx="70%" cy="40%" r="50%">
      <stop offset="0%" stop-color="#fff8e1" stop-opacity="0.25"/>
      <stop offset="50%" stop-color="#ffe082" stop-opacity="0.08"/>
      <stop offset="100%" stop-color="#ffb74d" stop-opacity="0"/>
    </radialGradient>
    """

    belt_additions = """
    <!-- Warm Flash Reflection on Right Belt Strap -->
    <path d="M 600 241 C 850 241 1010 214 1098 165 L 1082 281 C 985 323 812 341 600 341 Z" fill="url(#flashStrapReflect)" style="mix-blend-mode: screen;"/>
    """

    raw = raw.replace("</defs>", texture_defs + "\n</defs>")
    raw = raw.replace("</svg>", belt_additions + "\n</svg>")
    return raw


def _get_motor_svg(prefix: str) -> str:
    raw = _load_svg_asset("haptic-motor.svg")
    if not raw:
        return ""
    # Prefix IDs and url(# references to ensure uniqueness across left & right motor DOM instances
    raw = raw.replace('id="', f'id="{prefix}_')
    raw = raw.replace('url(#', f'url(#{prefix}_')
    return raw


# ---------------------------------------------------------------------------
# GET /live — Redesigned HapticGuide Live Belt Dashboard
# ---------------------------------------------------------------------------

@router.get("/live", response_class=HTMLResponse)
async def live_dashboard(request: Request) -> HTMLResponse:
    """Serve the live haptic belt visualization dashboard via Jinja2 template."""
    phone_svg = _get_phone_svg()
    belt_svg  = _get_belt_svg()
    lm_svg    = _get_motor_svg("lm")
    rm_svg    = _get_motor_svg("rm")

    return templates.TemplateResponse(
        request=request,
        name="live_dashboard.html",
        context={
            "phone_svg": phone_svg,
            "belt_svg": belt_svg,
            "lm_svg": lm_svg,
            "rm_svg": rm_svg,
        }
    )
