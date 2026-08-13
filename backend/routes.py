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

import base64
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, HTMLResponse

from shared_state import stream_stats, frame_slot
import globals


# ---------------------------------------------------------------------------
# Inline image helpers — embed belt.png and haptic_motor.png as data URIs
# so the dashboard HTML is fully self-contained (no static-file mount needed).
# ---------------------------------------------------------------------------

def _img_data_uri(filename: str) -> str:
    """Return a base64 data URI for an image file located next to routes.py."""
    img_path = Path(__file__).parent / filename
    try:
        data = img_path.read_bytes()
        b64  = base64.b64encode(data).decode("ascii")
        ext  = img_path.suffix.lstrip(".").lower()
        mime = "image/png" if ext == "png" else f"image/{ext}"
        return f"data:{mime};base64,{b64}"
    except FileNotFoundError:
        # Fallback: return a transparent 1×1 PNG so the page still loads
        return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


_BELT_IMG   = _img_data_uri("belt.png")
_MOTOR_IMG  = _img_data_uri("haptic_motor.png")

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
    Return full backend performance metrics, client connection state, target, and command.

    Response shape
    --------------
    {
        "camera_fps":         float,
        "yolo_fps":           float,
        "current_target":     str | dict | None,
        "current_command":    dict,
        "frame_age":          float,
        "frame_age_ms":       float,
        "recv_fps":           float,
        "ai_fps":             float,
        "yolo_time_ms":       float,
        "current_resolution": str,
        "client_ip":          str,
        "connected":          bool
    }
    """
    s = stream_stats.snapshot()
    ai_s = globals.get_api_stats()

    with globals.command_lock:
        cmd = dict(globals.latest_command)

    # Retrieve current target from computed globals or derive target position from latest_command
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


# ---------------------------------------------------------------------------
# GET /live  — real-time haptic belt dashboard
# ---------------------------------------------------------------------------

_LIVE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HapticGuide — Live Dashboard</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  background: #0d0d0d;
  color: #e0e0e0;
  font-family: 'Courier New', monospace;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-height: 100vh;
  padding: 40px 16px 56px;
  gap: 28px;
}}

/* ── Page heading ─────────────────────────────────────────────────────── */
.page-heading {{
  text-align: center;
  margin-bottom: 4px;
}}

h1 {{
  font-size: clamp(2rem, 6vw, 2.8rem);
  font-weight: bold;
  letter-spacing: 0.04em;
  line-height: 1;
}}

h1 .word-haptic {{
  color: #22d3ee;
  text-shadow: 0 0 18px rgba(34,211,238,0.45);
}}

h1 .word-guide {{
  color: #f0f0f0;
  margin-left: 0.18em;
}}

.page-subheading {{
  margin-top: 8px;
  font-size: 0.72rem;
  color: #3a3a3a;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-weight: normal;
}}

/* ── Content column — all panels aligned to same width ───────────────── */
.content {{
  width: 100%;
  max-width: 560px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}}

/* ── Status bar — thin strip, no card ────────────────────────────────── */
.status-bar {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 2px;
  border-bottom: 1px solid #222;
  font-size: 0.78rem;
  letter-spacing: 0.06em;
  background: transparent;
  transition: border-color 0.15s;
}}

.status-bar.safe {{
  border-bottom-color: #1e1e1e;
}}
.status-bar.active {{
  border-bottom-color: #3a6b3a;
}}

#status-text {{
  font-weight: bold;
  color: #555;
  transition: color 0.15s;
}}
.status-bar.active #status-text {{ color: #66bb6a; }}

#status-timestamp {{
  color: #333;
  font-size: 0.72rem;
  font-weight: normal;
  letter-spacing: 0.04em;
}}

/* ── Belt hero area — no border, just glow ───────────────────────────── */
.belt-hero {{
  background: radial-gradient(ellipse 70% 60% at 50% 50%,
                rgba(56,189,248,0.07) 0%,
                transparent 70%);
  padding: 16px 0 8px;
}}

/* ── Belt widget (UNCHANGED — do not touch below) ─────────────────────── */
.belt-widget {{
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  width: 100%;
}}

.belt-stage {{
  position: relative;
  width: 100%;
}}

.belt-img {{
  display: block;
  width: 100%;
  height: auto;
  user-select: none;
  pointer-events: none;
}}

.pulse-anchor {{
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  justify-content: center;
}}

.phone-anchor  {{ left: 50%; width: 80px;  height: 80px;  }}
.motor-left    {{ left: 8%;  width: 68px;  height: 80px;  }}
.motor-right   {{ left: 92%; width: 68px;  height: 80px;  }}

.motor-img {{
  width: 100%;
  height: 100%;
  object-fit: contain;
  filter: drop-shadow(0 0 4px rgba(0,0,0,0.5));
  position: relative;
  z-index: 2;
}}

.wave-ring {{
  position: absolute;
  top: 50%; left: 50%;
  width: 100%; height: 100%;
  border-radius: 50%;
  transform: translate(-50%, -50%) scale(0.4);
  opacity: 0;
  z-index: 1;
  border: 2px solid #38bdf8;
}}

.phone-anchor .wave-ring {{
  border-color: #a78bfa;
  width: 130%; height: 130%;
}}

.pulse-anchor .wave-ring:nth-child(1) {{ animation-delay: 0s;    }}
.pulse-anchor .wave-ring:nth-child(2) {{ animation-delay: 0.28s; }}
.pulse-anchor .wave-ring:nth-child(3) {{ animation-delay: 0.56s; }}

.pulse-anchor.active .wave-ring {{
  animation: haptic-pulse 1.2s ease-out infinite;
}}

@keyframes haptic-pulse {{
  0%   {{ transform: translate(-50%, -50%) scale(0.4); opacity: 0.85; }}
  100% {{ transform: translate(-50%, -50%) scale(2.0); opacity: 0;    }}
}}

@media (prefers-reduced-motion: reduce) {{
  .pulse-anchor.active .wave-ring {{ animation: none; opacity: 0.5; }}
}}

.belt-legend {{
  display: flex;
  gap: 18px;
  font-size: 0.7rem;
  color: #9ca3af;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}}

.legend-item {{ display: flex; align-items: center; gap: 6px; }}
.dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
.dot-lr     {{ background: #38bdf8; }}
.dot-center {{ background: #a78bfa; }}
/* ── END belt widget (unchanged) ─────────────────────────────────────── */

/* ── Telemetry panel ──────────────────────────────────────────────────── */
.telemetry {{
  background: transparent;
  padding: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: auto auto;
  gap: 12px;
}}

/* ── Stat cards (Current Target, Target Position) ─────────────────────── */
.card {{
  background: #161616;
  border: 1px solid #222;
  border-radius: 6px;
  padding: 14px 16px;
}}

.card .label {{
  font-size: 0.6rem;
  color: #555;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 10px;
}}

.card .value {{
  font-size: 1.15rem;
  font-weight: bold;
  color: #d0d0d0;
  word-break: break-all;
  line-height: 1.2;
}}

.card .value.highlight {{ color: #64b5f6; }}

/* ── PWM card — full-width second row ────────────────────────────────── */
.pwm-card {{
  grid-column: 1 / -1;
  background: #161616;
  border: 1px solid #222;
  border-radius: 6px;
  padding: 14px 16px;
}}

.pwm-card .label {{
  font-size: 0.6rem;
  color: #555;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 12px;
}}

/* Each PWM row: name | bar | number */
.pwm-row {{
  display: grid;
  grid-template-columns: 90px 1fr 36px;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px solid #1c1c1c;
}}

.pwm-row:last-child {{ border-bottom: none; }}

.motor-name {{
  font-size: 0.78rem;
  color: #555;
  letter-spacing: 0.04em;
}}

/* Color-coded motor names */
.motor-name.clr-lr     {{ color: #38bdf8; }}
.motor-name.clr-center {{ color: #a78bfa; }}

/* Mini intensity bar */
.pwm-bar-track {{
  height: 4px;
  background: #222;
  border-radius: 2px;
  overflow: hidden;
}}

.pwm-bar-fill {{
  height: 100%;
  width: 0%;
  border-radius: 2px;
  transition: width 0.1s ease;
}}

.pwm-bar-fill.clr-lr     {{ background: #38bdf8; }}
.pwm-bar-fill.clr-center {{ background: #a78bfa; }}

.motor-pwm {{
  font-size: 0.82rem;
  font-weight: bold;
  color: #e0e0e0;
  text-align: right;
}}

/* ── Footer ───────────────────────────────────────────────────────────── */
footer {{
  margin-top: 24px;
  font-size: 0.65rem;
  color: #333;
  letter-spacing: 0.06em;
}}

/* ── Mobile: stack to single column below 480px ──────────────────────── */
@media (max-width: 480px) {{
  .telemetry {{
    grid-template-columns: 1fr;
  }}
  .pwm-card {{
    grid-column: 1;
  }}
}}
</style>
</head>
<body>

<div class="page-heading">
  <h1><span class="word-haptic">Haptic</span><span class="word-guide">Guide</span></h1>
  <p class="page-subheading">Live belt telemetry &amp; obstacle feedback</p>
</div>

<div class="content">

  <!-- Status bar: merged status + timestamp -->
  <div class="status-bar safe" id="statusBar">
    <span id="status-text">No obstacle detected</span>
    <span id="status-timestamp">&#8212;</span>
  </div>

  <!-- Belt hero with radial glow -->
  <div class="belt-hero">
    <!-- ── Belt widget (UNCHANGED) ──────────────────────────────────────
         LEFT  → motor-left   (sky-blue rings)
         FRONT → phone-anchor (violet rings)
         RIGHT → motor-right  (sky-blue rings)
         BACK  → no visual
    ─────────────────────────────────────────────────────────────────── -->
    <div class="belt-widget">
      <div class="belt-stage">
        <img class="belt-img" src="{belt_src}" alt="Haptic belt" />

        <!-- Phone pulse (CENTER / front state) -->
        <div class="pulse-anchor phone-anchor" id="phoneAnchor">
          <div class="wave-ring"></div>
          <div class="wave-ring"></div>
          <div class="wave-ring"></div>
        </div>

        <!-- Left motor -->
        <div class="pulse-anchor motor-left" id="leftAnchor">
          <div class="wave-ring"></div>
          <div class="wave-ring"></div>
          <div class="wave-ring"></div>
          <img class="motor-img" src="{motor_src}" alt="Left motor" />
        </div>

        <!-- Right motor -->
        <div class="pulse-anchor motor-right" id="rightAnchor">
          <div class="wave-ring"></div>
          <div class="wave-ring"></div>
          <div class="wave-ring"></div>
          <img class="motor-img" src="{motor_src}" alt="Right motor" />
        </div>
      </div>

      <div class="belt-legend">
        <span class="legend-item"><i class="dot dot-lr"></i>Left / Right motor</span>
        <span class="legend-item"><i class="dot dot-center"></i>Center (phone)</span>
      </div>
    </div>
  </div>

  <!-- Telemetry panel: 2-col grid -->
  <div class="telemetry">

    <!-- Row 1: stat cards -->
    <div class="card">
      <div class="label">Current Target</div>
      <div class="value highlight" id="card-target">&#8212;</div>
    </div>
    <div class="card">
      <div class="label">Target Position</div>
      <div class="value" id="card-position">&#8212;</div>
    </div>

    <!-- Row 2: PWM card full-width -->
    <div class="pwm-card">
      <div class="label">Current PWM Values</div>

      <div class="pwm-row" id="row-front">
        <span class="motor-name clr-center">Front (phone)</span>
        <div class="pwm-bar-track">
          <div class="pwm-bar-fill clr-center" id="bar-front"></div>
        </div>
        <span class="motor-pwm" id="tval-front">0</span>
      </div>

      <div class="pwm-row" id="row-left">
        <span class="motor-name clr-lr">Left</span>
        <div class="pwm-bar-track">
          <div class="pwm-bar-fill clr-lr" id="bar-left"></div>
        </div>
        <span class="motor-pwm" id="tval-left">0</span>
      </div>

      <div class="pwm-row" id="row-right">
        <span class="motor-name clr-lr">Right</span>
        <div class="pwm-bar-track">
          <div class="pwm-bar-fill clr-lr" id="bar-right"></div>
        </div>
        <span class="motor-pwm" id="tval-right">0</span>
      </div>
    </div>

  </div><!-- /telemetry -->

</div><!-- /content -->

<footer>Polling /cmd every 50 ms &middot; /stats every 500 ms</footer>

<script>
/**
 * Belt state mapping:
 *   cmd.left  > 0  → pulse left motor image
 *   cmd.right > 0  → pulse right motor image
 *   cmd.front > 0  → pulse phone (CENTER feedback comes from phone vibration)
 *   cmd.back       → ignored (belt has no rear physical motor)
 */
function updateBeltState(cmd) {{
  document.getElementById('leftAnchor').classList.toggle(
    'active', !!(cmd && cmd.left  > 0));
  document.getElementById('rightAnchor').classList.toggle(
    'active', !!(cmd && cmd.right > 0));
  document.getElementById('phoneAnchor').classList.toggle(
    'active', !!(cmd && cmd.front > 0));
}}

function setPwmRow(name, pwm) {{
  const tval = document.getElementById('tval-' + name);
  const bar  = document.getElementById('bar-'  + name);
  const row  = document.getElementById('row-'  + name);
  tval.textContent      = pwm;
  bar.style.width       = (Math.min(pwm, 255) / 255 * 100).toFixed(1) + '%';
  if (pwm > 0) {{ row.classList.add('active-row');    }}
  else         {{ row.classList.remove('active-row'); }}
}}

function timestamp() {{
  return new Date().toLocaleTimeString('en-GB', {{
    hour12: false, hour: '2-digit', minute: '2-digit',
    second: '2-digit', fractionalSecondDigits: 2
  }});
}}

async function pollCmd() {{
  try {{
    const data = await fetch('/cmd').then(r => r.json());

    updateBeltState(data);
    ['front', 'left', 'right'].forEach(m => setPwmRow(m, data[m] ?? 0));

    const anyActive = ['front', 'left', 'right'].some(m => (data[m] ?? 0) > 0);
    const bar = document.getElementById('statusBar');
    const txt = document.getElementById('status-text');
    if (anyActive) {{
      bar.className  = 'status-bar active';
      txt.textContent = '\u26a0 Obstacle detected';
    }} else {{
      bar.className  = 'status-bar safe';
      txt.textContent = 'No obstacle detected';
    }}

    document.getElementById('status-timestamp').textContent = timestamp();
  }} catch (_) {{}}
}}

async function pollStats() {{
  try {{
    const data   = await fetch('/stats').then(r => r.json());
    const target = data.current_target;

    if (target && typeof target === 'object') {{
      document.getElementById('card-target').textContent =
        target.class_name ?? '\u2014';
      document.getElementById('card-position').textContent =
        target.position   ?? '\u2014';
    }} else if (typeof target === 'string' && target.length) {{
      document.getElementById('card-target').textContent   = target;
      document.getElementById('card-position').textContent = '\u2014';
    }} else {{
      document.getElementById('card-target').textContent   = '\u2014';
      document.getElementById('card-position').textContent = '\u2014';
    }}
  }} catch (_) {{}}
}}

pollCmd();
pollStats();
setInterval(pollCmd,   50);
setInterval(pollStats, 500);
</script>
</body>
</html>
"""


@router.get("/live", response_class=HTMLResponse)
async def live_dashboard() -> HTMLResponse:
    """
    Serve the real-time haptic belt visualisation dashboard.

    The page polls GET /cmd every 50 ms (20 FPS) for motor PWM state and
    GET /stats every 500 ms for current target information.
    No external frameworks. No page refresh required.

    Open in any browser:
        http://localhost:8000/live
    """
    html = _LIVE_HTML.format(belt_src=_BELT_IMG, motor_src=_MOTOR_IMG)
    return HTMLResponse(content=html, status_code=200)
