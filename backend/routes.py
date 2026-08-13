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
GET /live   — real-time haptic belt visual dashboard (redesigned UI).
"""

import base64
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, HTMLResponse

from shared_state import stream_stats, frame_slot
import globals


router = APIRouter()


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
async def live_dashboard() -> HTMLResponse:
    """Serve the redesigned live haptic belt visualization dashboard."""
    phone_svg = _get_phone_svg()
    belt_svg  = _get_belt_svg()
    lm_svg    = _get_motor_svg("lm")
    rm_svg    = _get_motor_svg("rm")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HapticGuide — Live Belt Dashboard</title>
<style>
/* ── Design System & Base Reset ──────────────────────────────────────── */
* {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}

:root {{
  --bg-dark: #07080a;
  --bg-card: #0d0f13;
  --border-card: #181b22;
  --cyan-accent: #38bdf8;
  --cyan-glow: rgba(56, 189, 248, 0.45);
  --purple-accent: #a855f7;
  --purple-glow: rgba(168, 85, 247, 0.45);
  --gold-accent: #f59e0b;
  --text-primary: #f3f4f6;
  --text-secondary: #9ca3af;
  --text-muted: #4b5563;
  --success: #10b981;
  --warning: #f59e0b;
}}

body {{
  background-color: var(--bg-dark);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 16px 40px;
  gap: 20px;
  overflow-x: hidden;
}}

/* ── Typography & Header (Matching ref_img/3.png) ───────────────────── */
.header {{
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}}

.title {{
  font-size: clamp(1.8rem, 5vw, 2.6rem);
  font-weight: 900;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  line-height: 1;
}}

.title .word-haptic {{
  color: var(--cyan-accent);
}}

.title .word-guide {{
  color: var(--text-primary);
  margin-left: 0.05em;
}}

.subtitle {{
  font-size: 0.72rem;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--text-secondary);
  font-weight: 500;
  opacity: 0.75;
}}

.phone-status-badge {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(17, 19, 23, 0.85);
  border: 1px solid var(--border-card);
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 0.65rem;
  letter-spacing: 0.16em;
  font-weight: 600;
  color: var(--text-secondary);
  backdrop-filter: blur(8px);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
  margin-top: 4px;
}}

.status-dot {{
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
}}

/* ── Main Dashboard Container ───────────────────────────────────────── */
.dashboard-container {{
  width: 100%;
  max-width: 840px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
}}

/* ── Product Showcase Stage (Belt is Primary reference; Phone is ~44% width) ── */
.product-showcase {{
  position: relative;
  width: min(88vw, 740px);
  margin: 10px auto 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  perspective: 1200px;
}}

/* Physical Phone Component (ALWAYS in Popped-Out Foreground State; Zero Hover Change) */
.phone-wrapper {{
  position: absolute;
  top: -65px;
  left: 50%;
  transform: translateX(-50%);
  width: clamp(210px, 44%, 330px);
  z-index: 30;
  perspective: 1200px;
  transform-style: preserve-3d;
}}

.phone-svg-container {{
  width: 100%;
  position: relative;
  border-radius: 38px;
  /* Persistent elevated 3D depth state */
  transform: perspective(1000px) scale(1.06) translateZ(28px) rotateX(1deg) rotateY(-0.5deg);
  transform-style: preserve-3d;
  filter: 
    drop-shadow(0 30px 55px rgba(0, 0, 0, 0.98))
    drop-shadow(0 14px 24px rgba(0, 0, 0, 0.9));
  will-change: transform;
}}

/* Subtle High-Frequency Physical Phone Vibration Animation (For FRONT Obstacles) */
@keyframes phonePhysicalVibration {{
  0%   {{ transform: perspective(1000px) scale(1.06) translateZ(28px) rotateX(1deg) rotateY(-0.5deg) translate(0, 0); }}
  20%  {{ transform: perspective(1000px) scale(1.06) translateZ(28px) rotateX(1deg) rotateY(-0.5deg) translate(-1px, 0.5px); }}
  40%  {{ transform: perspective(1000px) scale(1.06) translateZ(28px) rotateX(1deg) rotateY(-0.5deg) translate(1px, -0.5px); }}
  60%  {{ transform: perspective(1000px) scale(1.06) translateZ(28px) rotateX(1deg) rotateY(-0.5deg) translate(-0.8px, -0.4px); }}
  80%  {{ transform: perspective(1000px) scale(1.06) translateZ(28px) rotateX(1deg) rotateY(-0.5deg) translate(0.8px, 0.4px); }}
  100% {{ transform: perspective(1000px) scale(1.06) translateZ(28px) rotateX(1deg) rotateY(-0.5deg) translate(0, 0); }}
}}

.phone-wrapper.vibrating .phone-svg-container {{
  animation: phonePhysicalVibration 0.06s infinite linear;
  filter: 
    drop-shadow(0 30px 55px rgba(0, 0, 0, 0.98))
    drop-shadow(0 0 15px rgba(56, 189, 248, 0.5));
}}

.phone-svg-container svg {{
  width: 100%;
  height: auto;
  display: block;
  overflow: visible;
}}

/* Belt Component (Primary Hardware Reference) */
.belt-wrapper {{
  position: relative;
  width: 100%;
  aspect-ratio: 1200 / 430;
  z-index: 10;
  filter: drop-shadow(0 22px 34px rgba(0, 0, 0, 0.88));
}}

.belt-svg {{
  width: 100%;
  height: 100%;
  display: block;
}}

.belt-svg svg {{
  width: 100%;
  height: 100%;
  display: block;
}}

/* ── Motor Units (Physically Clipped to Curved Belt Surface with Mirrored 3D Perspective) ── */
.motor {{
  position: absolute;
  top: 57%;
  width: 11.5%;
  aspect-ratio: 120 / 80;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 15;
  perspective: 600px;
  transform-style: preserve-3d;
}}

/* Left Motor: Curved 3D rotation following left belt ellipse strap */
.motor-left {{
  left: 12.1%;
  transform: translate(-50%, -50%) perspective(600px) rotateY(18deg) rotateZ(5deg) translateZ(8px);
  transform-origin: center right;
  filter: 
    drop-shadow(-4px 8px 12px rgba(0, 0, 0, 0.9))
    drop-shadow(0 2px 4px rgba(0, 0, 0, 0.7));
}}

/* Right Motor: Mirrored 3D rotation following right belt ellipse strap */
.motor-right {{
  left: 87.9%;
  transform: translate(-50%, -50%) perspective(600px) rotateY(-18deg) rotateZ(-5deg) translateZ(8px);
  transform-origin: center left;
  filter: 
    drop-shadow(4px 8px 12px rgba(0, 0, 0, 0.9))
    drop-shadow(0 2px 4px rgba(0, 0, 0, 0.7));
}}

.motor-vibe-wrapper {{
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  will-change: transform, opacity;
  transition: filter 0.2s ease;
}}

.motor svg {{
  width: 100%;
  height: 100%;
  display: block;
}}

/* Micro-Vibration Animation for Belt Motors */
@keyframes hapticVibration {{
  0%   {{ transform: translate(0, 0) scale(1); opacity: 1; }}
  20%  {{ transform: translate(calc(-0.8px * var(--vib-scale, 1)), calc(0.4px * var(--vib-scale, 1))) scale(1.008); opacity: 0.98; }}
  40%  {{ transform: translate(calc(0.8px * var(--vib-scale, 1)), calc(-0.4px * var(--vib-scale, 1))) scale(0.992); opacity: 1; }}
  60%  {{ transform: translate(calc(-0.6px * var(--vib-scale, 1)), 0) scale(1.005); opacity: 0.98; }}
  80%  {{ transform: translate(calc(0.6px * var(--vib-scale, 1)), calc(0.4px * var(--vib-scale, 1))) scale(1); opacity: 1; }}
  100% {{ transform: translate(0, 0) scale(1); opacity: 1; }}
}}

.motor-vibe-wrapper.active {{
  animation: hapticVibration var(--vibrate-speed, 0.07s) infinite linear;
  filter: drop-shadow(0 2px 10px var(--motor-glow-color, var(--cyan-accent)));
}}

.motor-left .motor-vibe-wrapper.active {{ --motor-glow-color: rgba(56, 189, 248, 0.65); }}
.motor-right .motor-vibe-wrapper.active {{ --motor-glow-color: rgba(168, 85, 247, 0.65); }}

.motor-wave-rings {{
  position: absolute;
  top: 50%;
  left: 50%;
  width: 140%;
  height: 140%;
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 5;
}}

.wave-ring-el {{
  position: absolute;
  top: 50%;
  left: 50%;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  transform: translate(-50%, -50%) scale(0.5);
  opacity: 0;
  border: 2px solid var(--cyan-accent);
}}

.motor-right .wave-ring-el {{ border-color: var(--purple-accent); }}

.motor-vibe-wrapper.active .wave-ring-el {{
  animation: wave-expand var(--wave-speed, 1s) cubic-bezier(0.1, 0.8, 0.3, 1) infinite;
}}

.motor-vibe-wrapper.active .wave-ring-el:nth-child(1) {{ animation-delay: 0s; }}
.motor-vibe-wrapper.active .wave-ring-el:nth-child(2) {{ animation-delay: 0.33s; }}
.motor-vibe-wrapper.active .wave-ring-el:nth-child(3) {{ animation-delay: 0.66s; }}

@keyframes wave-expand {{
  0% {{ transform: translate(-50%, -50%) scale(0.4); opacity: 0.95; }}
  100% {{ transform: translate(-50%, -50%) scale(2.2); opacity: 0; }}
}}

/* ── Hero Footer Caption & Legend ───────────────────────────────────── */
.hero-footer {{
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}}

.hero-caption {{
  font-size: 0.82rem;
  color: var(--text-secondary);
  letter-spacing: 0.05em;
}}

.motor-legend {{
  display: flex;
  align-items: center;
  gap: 18px;
  font-size: 0.68rem;
  color: var(--text-secondary);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-weight: 600;
}}

.legend-badge {{
  display: flex;
  align-items: center;
  gap: 7px;
}}

.legend-dot {{
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}}

.legend-dot.left {{ background: var(--cyan-accent); }}
.legend-dot.right {{ background: var(--purple-accent); }}

/* ── Minimal Professional Telemetry Panel (No Emojis) ───────────────── */
.telemetry-panel {{
  width: 100%;
  max-width: 840px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 4px;
}}

.telemetry-grid-card {{
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 16px;
  padding: 20px 24px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px 24px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
}}

.tele-item {{
  display: flex;
  align-items: center;
  gap: 14px;
}}

.tele-icon {{
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}}

.tele-icon svg {{
  width: 18px;
  height: 18px;
  stroke-width: 2;
  fill: none;
  stroke: currentColor;
}}

.tele-icon.cyan {{ color: var(--cyan-accent); border-color: rgba(56, 189, 248, 0.2); background: rgba(56, 189, 248, 0.04); }}
.tele-icon.purple {{ color: var(--purple-accent); border-color: rgba(168, 85, 247, 0.2); background: rgba(168, 85, 247, 0.04); }}
.tele-icon.green {{ color: var(--success); border-color: rgba(16, 185, 129, 0.2); background: rgba(16, 185, 129, 0.04); }}
.tele-icon.gold {{ color: var(--gold-accent); border-color: rgba(245, 158, 11, 0.2); background: rgba(245, 158, 11, 0.04); }}

.tele-content {{
  display: flex;
  flex-direction: column;
  gap: 2px;
}}

.tele-label {{
  font-size: 0.6rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-weight: 700;
}}

.tele-value {{
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}}

.tele-value.cyan {{ color: var(--cyan-accent); }}
.tele-value.purple {{ color: var(--purple-accent); }}
.tele-value.green {{ color: var(--success); }}
.tele-value.warning {{ color: var(--warning); }}
.tele-value.gold {{ color: var(--gold-accent); font-family: 'Courier New', monospace; }}

/* Full-width PWM Motor Intensity Card */
.pwm-card {{
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 14px;
  padding: 18px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}}

.pwm-row {{
  display: grid;
  grid-template-columns: 110px 1fr 40px;
  align-items: center;
  gap: 14px;
}}

.pwm-motor-name {{
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.08em;
}}

.pwm-motor-name.left {{ color: var(--cyan-accent); }}
.pwm-motor-name.right {{ color: var(--purple-accent); }}

.pwm-track {{
  height: 5px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 3px;
  overflow: hidden;
}}

.pwm-fill {{
  height: 100%;
  width: 0%;
  border-radius: 3px;
  transition: width 0.1s ease;
}}

.pwm-fill.left {{ background: var(--cyan-accent); }}
.pwm-fill.right {{ background: var(--purple-accent); }}

.pwm-num {{
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--text-primary);
  text-align: right;
  font-family: 'Courier New', monospace;
}}

/* Footer */
.system-stats {{
  font-size: 0.65rem;
  color: var(--text-muted);
  text-align: center;
  letter-spacing: 0.08em;
}}

/* Responsive Breakpoints & Overflow Prevention */
@media (max-width: 768px) {{
  .phone-wrapper {{ width: clamp(180px, 45%, 290px); top: -50px; }}
}}

@media (max-width: 540px) {{
  body {{ padding: 20px 12px 30px; gap: 16px; }}
  .telemetry-grid-card {{ grid-template-columns: 1fr; gap: 16px; padding: 16px; }}
  .phone-wrapper {{ width: clamp(160px, 48%, 250px); top: -42px; }}
  .pwm-row {{ grid-template-columns: 85px 1fr 36px; gap: 10px; }}
  .tele-item {{ gap: 10px; }}
}}
</style>
</head>
<body>

  <!-- Header (Matching ref_img/3.png) -->
  <header class="header">
    <h1 class="title">
      <span class="word-haptic">HAPTIC</span><span class="word-guide">GUIDE</span>
    </h1>
    <div class="subtitle">LIVE BELT DASHBOARD</div>
    <div class="phone-status-badge">
      <span class="status-dot"></span>
      <span id="phone-status-text">PHONE CONNECTED</span>
    </div>
  </header>

  <!-- Main Dashboard Container -->
  <main class="dashboard-container">

    <!-- Product Showcase Stage (Phone inside Belt Loop) -->
    <section class="product-showcase">

      <!-- Phone Component (Nested inside belt loop, ending right above HG Buckle) -->
      <div class="phone-wrapper">
        <div class="phone-svg-container">
          {phone_svg}
        </div>
      </div>

      <!-- Belt Component (Primary Hardware Anchor) -->
      <div class="belt-wrapper">
        <div class="belt-svg">
          {belt_svg}
        </div>

        <!-- Left Motor -->
        <div class="motor motor-left" id="leftMotor">
          <div class="motor-vibe-wrapper">
            <div class="motor-wave-rings">
              <div class="wave-ring-el"></div>
              <div class="wave-ring-el"></div>
              <div class="wave-ring-el"></div>
            </div>
            {lm_svg}
          </div>
        </div>

        <!-- Right Motor -->
        <div class="motor motor-right" id="rightMotor">
          <div class="motor-vibe-wrapper">
            <div class="motor-wave-rings">
              <div class="wave-ring-el"></div>
              <div class="wave-ring-el"></div>
              <div class="wave-ring-el"></div>
            </div>
            {rm_svg}
          </div>
        </div>
      </div>

    </section>

    <!-- Hero Footer Caption & Legend -->
    <div class="hero-footer">
      <div class="hero-caption">Feel the vibration to navigate</div>
      <div class="motor-legend">
        <div class="legend-badge">
          <span class="legend-dot left"></span>
          <span>LEFT MOTOR</span>
        </div>
        <span style="opacity:0.3">|</span>
        <div class="legend-badge">
          <span class="legend-dot right"></span>
          <span>RIGHT MOTOR</span>
        </div>
      </div>
    </div>

    <!-- Minimal Engineering Telemetry Panel (No Emojis) -->
    <section class="telemetry-panel">

      <!-- 2x2 Telemetry Grid Card -->
      <div class="telemetry-grid-card">
        
        <!-- 1. Current Target -->
        <div class="tele-item">
          <div class="tele-icon cyan">
            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/></svg>
          </div>
          <div class="tele-content">
            <div class="tele-label">CURRENT TARGET</div>
            <div class="tele-value cyan" id="val-target">&#8212;</div>
          </div>
        </div>

        <!-- 2. Target Position -->
        <div class="tele-item">
          <div class="tele-icon purple">
            <svg viewBox="0 0 24 24"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
          </div>
          <div class="tele-content">
            <div class="tele-label">TARGET POSITION</div>
            <div class="tele-value purple" id="val-position">&#8212;</div>
          </div>
        </div>

        <!-- 3. Obstacle Status -->
        <div class="tele-item">
          <div class="tele-icon green" id="status-icon-box">
            <svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>
          </div>
          <div class="tele-content">
            <div class="tele-label">OBSTACLE STATUS</div>
            <div class="tele-value green" id="val-obstacle">SAFE</div>
          </div>
        </div>

        <!-- 4. Last Update -->
        <div class="tele-item">
          <div class="tele-icon gold">
            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          </div>
          <div class="tele-content">
            <div class="tele-label">LAST UPDATE</div>
            <div class="tele-value gold" id="status-timestamp">&#8212;</div>
          </div>
        </div>

      </div>

      <!-- PWM Motor Intensity Card -->
      <div class="pwm-card">
        <div class="tele-label">VIBRATION MOTOR INTENSITY (PWM)</div>

        <!-- Left Motor Row -->
        <div class="pwm-row">
          <span class="pwm-motor-name left">LEFT MOTOR</span>
          <div class="pwm-track">
            <div class="pwm-fill left" id="bar-left"></div>
          </div>
          <span class="pwm-num" id="val-pwm-left">0</span>
        </div>

        <!-- Right Motor Row -->
        <div class="pwm-row">
          <span class="pwm-motor-name right">RIGHT MOTOR</span>
          <div class="pwm-track">
            <div class="pwm-fill right" id="bar-right"></div>
          </div>
          <span class="pwm-num" id="val-pwm-right">0</span>
        </div>
      </div>

    </section>

  </main>

  <footer class="system-stats" id="system-stats">
    Polling /cmd @ 20 Hz &middot; /stats @ 2 Hz
  </footer>

<script>
/**
 * Update Motor Component Visual Vibration & State based on PWM value (0-255)
 */
function setMotorState(motorId, prefix, pwm) {{
  const motorEl = document.getElementById(motorId);
  if (!motorEl) return;
  const vibeWrapper = motorEl.querySelector('.motor-vibe-wrapper');
  if (!vibeWrapper) return;

  const isActive = pwm > 0;
  const intensity = Math.min(Math.max(pwm, 0), 255);

  if (isActive) {{
    vibeWrapper.classList.add('active');

    let speed = '0.09s';
    let scale = 0.7;
    let glow = '6px';
    let waveOpacity = 0.4;
    let waveSpeed = '1.2s';

    if (intensity <= 80) {{
      speed = '0.09s';
      scale = 0.7;
      glow = '6px';
      waveOpacity = 0.4;
      waveSpeed = '1.2s';
    }} else if (intensity <= 170) {{
      speed = '0.07s';
      scale = 1.15;
      glow = '12px';
      waveOpacity = 0.75;
      waveSpeed = '0.9s';
    }} else {{
      speed = '0.05s';
      scale = 1.6;
      glow = '18px';
      waveOpacity = 1.0;
      waveSpeed = '0.65s';
    }}

    vibeWrapper.style.setProperty('--vibrate-speed', speed);
    vibeWrapper.style.setProperty('--vib-scale', scale);
    vibeWrapper.style.setProperty('--glow-size', glow);
    vibeWrapper.style.setProperty('--wave-speed', waveSpeed);

    // Light up SVG LED indicator
    const led = document.getElementById(prefix + '_motor-led');
    if (led) {{
      led.setAttribute('fill', prefix === 'lm' ? '#38bdf8' : '#a855f7');
    }}

    // Control SVG Vibration Arcs inside motor SVG
    const vibLeftArc  = document.getElementById(prefix + '_vibration-left');
    const vibRightArc = document.getElementById(prefix + '_vibration-right');
    if (vibLeftArc)  vibLeftArc.style.opacity  = waveOpacity.toString();
    if (vibRightArc) vibRightArc.style.opacity = waveOpacity.toString();

  }} else {{
    vibeWrapper.classList.remove('active');
    vibeWrapper.style.removeProperty('--vibrate-speed');
    vibeWrapper.style.removeProperty('--vib-scale');
    vibeWrapper.style.removeProperty('--glow-size');
    vibeWrapper.style.removeProperty('--wave-speed');

    // Turn off SVG LED
    const led = document.getElementById(prefix + '_motor-led');
    if (led) {{
      led.setAttribute('fill', '#222');
    }}

    // Hide SVG Vibration Arcs
    const vibLeftArc  = document.getElementById(prefix + '_vibration-left');
    const vibRightArc = document.getElementById(prefix + '_vibration-right');
    if (vibLeftArc)  vibLeftArc.style.opacity  = '0';
    if (vibRightArc) vibRightArc.style.opacity = '0';
  }}
}}

function updatePwmBar(name, pwm) {{
  const bar = document.getElementById('bar-' + name);
  const num = document.getElementById('val-pwm-' + name);
  if (num) num.textContent = pwm;
  if (bar) bar.style.width = ((Math.min(pwm, 255) / 255) * 100).toFixed(1) + '%';
}}

function getTimestamp() {{
  const now = new Date();
  const hrs = String(now.getHours()).padStart(2, '0');
  const mins = String(now.getMinutes()).padStart(2, '0');
  const secs = String(now.getSeconds()).padStart(2, '0');
  const ms = String(Math.floor(now.getMilliseconds() / 10)).padStart(2, '0');
  return `${{hrs}}:${{mins}}:${{secs}}.${{ms}}`;
}}

async function pollCmd() {{
  try {{
    const data = await fetch('/cmd').then(r => r.json());

    const leftPwm  = data.left  ?? 0;
    const rightPwm = data.right ?? 0;
    const frontPwm = data.front ?? 0;
    const backPwm  = data.back  ?? 0;

    // ── NEW 2-MOTOR + PHONE HAPTIC OUTPUT MAPPING ────────────────────
    let phoneVibrating = false;
    let activeLeftPwm  = 0;
    let activeRightPwm = 0;

    // 1. FRONT Obstacle -> Phone Vibration ONLY (Belt motors OFF)
    if (frontPwm > 0) {{
      phoneVibrating = true;
      activeLeftPwm  = 0;
      activeRightPwm = 0;
    }} 
    // 2. LEFT Obstacle -> Left Belt Motor ONLY (Phone OFF, Right OFF)
    else if (leftPwm > 0) {{
      phoneVibrating = false;
      activeLeftPwm  = leftPwm;
      activeRightPwm = 0;
    }} 
    // 3. RIGHT Obstacle -> Right Belt Motor ONLY (Phone OFF, Left OFF)
    else if (rightPwm > 0) {{
      phoneVibrating = false;
      activeLeftPwm  = 0;
      activeRightPwm = rightPwm;
    }} 
    // 4. BACK Obstacle -> Isolated for future specification (Unchanged)
    else if (backPwm > 0) {{
      phoneVibrating = false;
      activeLeftPwm  = 0;
      activeRightPwm = 0;
    }}

    // Update Phone Vibration State (High-frequency CSS oscillation)
    const phoneWrapper = document.querySelector('.phone-wrapper');
    const phoneStatusText = document.getElementById('phone-status-text');

    if (phoneWrapper) {{
      if (phoneVibrating) {{
        phoneWrapper.classList.add('vibrating');
        if (phoneStatusText) phoneStatusText.textContent = 'PHONE VIBRATING (FRONT)';
      }} else {{
        phoneWrapper.classList.remove('vibrating');
        if (phoneStatusText) phoneStatusText.textContent = 'PHONE CONNECTED';
      }}
    }}

    // Drive Left & Right belt motors independently
    setMotorState('leftMotor',  'lm', activeLeftPwm);
    setMotorState('rightMotor', 'rm', activeRightPwm);

    // Update PWM progress bars & numeric values
    updatePwmBar('left',  activeLeftPwm);
    updatePwmBar('right', activeRightPwm);

    // Update Obstacle Alert Status
    const anyActive = leftPwm > 0 || rightPwm > 0 || frontPwm > 0 || backPwm > 0;
    const obstacleVal = document.getElementById('val-obstacle');
    const obstacleBox = document.getElementById('status-icon-box');

    if (anyActive) {{
      if (obstacleVal) {{ obstacleVal.textContent = 'DETECTED'; obstacleVal.className = 'tele-value warning'; }}
      if (obstacleBox) {{ obstacleBox.innerHTML = '<svg viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'; obstacleBox.className = 'tele-icon gold'; }}
    }} else {{
      if (obstacleVal) {{ obstacleVal.textContent = 'SAFE'; obstacleVal.className = 'tele-value green'; }}
      if (obstacleBox) {{ obstacleBox.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>'; obstacleBox.className = 'tele-icon green'; }}
    }}

    const tsEl = document.getElementById('status-timestamp');
    if (tsEl) tsEl.textContent = getTimestamp();
  }} catch (_) {{}}
}}

async function pollStats() {{
  try {{
    const data = await fetch('/stats').then(r => r.json());
    const target = data.current_target;

    const valTarget   = document.getElementById('val-target');
    const valPosition = document.getElementById('val-position');

    if (target && typeof target === 'object') {{
      if (valTarget)   valTarget.textContent   = (target.class_name || '\u2014').toUpperCase();
      if (valPosition) valPosition.textContent = (target.position || '0\u00B0').toUpperCase();
    }} else if (typeof target === 'string' && target.length) {{
      if (valTarget)   valTarget.textContent   = target.toUpperCase();
      if (valPosition) valPosition.textContent = '0\u00B0';
    }} else {{
      if (valTarget)   valTarget.textContent   = 'CENTER';
      if (valPosition) valPosition.textContent = '0\u00B0';
    }}

    const statsFooter = document.getElementById('system-stats');
    if (statsFooter && data.yolo_fps !== undefined) {{
      statsFooter.textContent = `YOLO: ${{data.yolo_fps}} FPS | Cam: ${{data.camera_fps}} FPS | Age: ${{data.frame_age_ms}}ms`;
    }}
  }} catch (_) {{}}
}}

// Initialize polling
pollCmd();
pollStats();
setInterval(pollCmd, 50);
setInterval(pollStats, 500);
</script>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)
