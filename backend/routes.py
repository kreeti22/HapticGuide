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
from fastapi.responses import JSONResponse, HTMLResponse

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
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: #0d0d0d;
  color: #e0e0e0;
  font-family: 'Courier New', monospace;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-height: 100vh;
  padding: 32px 16px;
  gap: 28px;
}

h1 {
  font-size: 1.4rem;
  letter-spacing: 0.12em;
  color: #64b5f6;
  text-transform: uppercase;
}

/* Belt visualisation */
.belt-grid {
  display: grid;
  grid-template-columns: 80px 80px 80px;
  grid-template-rows:    80px 80px 80px;
  gap: 12px;
  place-items: center;
}

.motor {
  width: 72px; height: 72px;
  border-radius: 50%;
  border: 3px solid #444;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-size: 0.65rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-weight: bold;
  transition: background 0.1s, box-shadow 0.1s, border-color 0.1s;
  user-select: none;
}

.motor .pwm-val {
  font-size: 0.75rem;
  margin-top: 4px;
  color: #bbb;
}

.motor.inactive {
  background: #222;
  border-color: #444;
  color: #555;
}
.motor.inactive .pwm-val { color: #444; }

.motor.active {
  background: #1b4d1b;
  border-color: #4caf50;
  color: #4caf50;
  box-shadow: 0 0 18px 4px rgba(76, 175, 80, 0.55);
}
.motor.active .pwm-val { color: #a5d6a7; }

.front { grid-column: 2; grid-row: 1; }
.left  { grid-column: 1; grid-row: 2; }
.right { grid-column: 3; grid-row: 2; }
.back  { grid-column: 2; grid-row: 3; }

/* Status banner */
#status-banner {
  font-size: 1.05rem;
  font-weight: bold;
  letter-spacing: 0.08em;
  padding: 10px 28px;
  border-radius: 6px;
  text-align: center;
  min-width: 260px;
  transition: background 0.15s, color 0.15s;
}

#status-banner.safe {
  background: #1a1a1a;
  color: #888;
  border: 1px solid #333;
}
#status-banner.active {
  background: #1b3a1b;
  color: #66bb6a;
  border: 1px solid #4caf50;
  box-shadow: 0 0 12px rgba(76, 175, 80, 0.3);
}

/* Info cards */
.cards {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  justify-content: center;
  max-width: 600px;
  width: 100%;
}

.card {
  background: #161616;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 14px 20px;
  min-width: 160px;
  flex: 1;
}

.card .label {
  font-size: 0.65rem;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 6px;
}

.card .value {
  font-size: 1.0rem;
  color: #e0e0e0;
  word-break: break-all;
}

.card .value.highlight { color: #64b5f6; }

/* PWM table */
.pwm-table {
  background: #161616;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 14px 20px;
  min-width: 220px;
}

.pwm-table .label {
  font-size: 0.65rem;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 10px;
}

.pwm-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
  padding: 3px 0;
  border-bottom: 1px solid #1e1e1e;
}

.pwm-row:last-child { border-bottom: none; }
.pwm-row .motor-name { color: #888; }
.pwm-row .motor-pwm  { color: #e0e0e0; font-weight: bold; }
.pwm-row.active-row  .motor-name { color: #66bb6a; }
.pwm-row.active-row  .motor-pwm  { color: #4caf50; }

/* Raw JSON */
pre#raw-json {
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  padding: 14px 18px;
  font-size: 0.78rem;
  color: #80cbc4;
  max-width: 360px;
  width: 100%;
  overflow-x: auto;
  line-height: 1.6;
}

footer {
  font-size: 0.65rem;
  color: #444;
  letter-spacing: 0.06em;
}
</style>
</head>
<body>

<h1>&#9889; HapticGuide &#8212; Live Belt Dashboard</h1>

<div id="status-banner" class="safe">No obstacle detected</div>

<!-- Belt visualisation -->
<div class="belt-grid">
  <div id="m-front" class="motor front inactive">
    FRONT <span class="pwm-val" id="pwm-front">0</span>
  </div>
  <div id="m-left" class="motor left inactive">
    LEFT <span class="pwm-val" id="pwm-left">0</span>
  </div>
  <div id="m-right" class="motor right inactive">
    RIGHT <span class="pwm-val" id="pwm-right">0</span>
  </div>
  <div id="m-back" class="motor back inactive">
    BACK <span class="pwm-val" id="pwm-back">0</span>
  </div>
</div>

<!-- Info cards + PWM table -->
<div class="cards">
  <div class="card">
    <div class="label">Current Target</div>
    <div class="value highlight" id="card-target">&#8212;</div>
  </div>
  <div class="card">
    <div class="label">Target Position</div>
    <div class="value" id="card-position">&#8212;</div>
  </div>
  <div class="card">
    <div class="label">Last Update</div>
    <div class="value" id="card-updated">&#8212;</div>
  </div>

  <div class="pwm-table">
    <div class="label">Current PWM Values</div>
    <div class="pwm-row" id="row-front">
      <span class="motor-name">Front</span>
      <span class="motor-pwm" id="tval-front">0</span>
    </div>
    <div class="pwm-row" id="row-left">
      <span class="motor-name">Left</span>
      <span class="motor-pwm" id="tval-left">0</span>
    </div>
    <div class="pwm-row" id="row-right">
      <span class="motor-name">Right</span>
      <span class="motor-pwm" id="tval-right">0</span>
    </div>
    <div class="pwm-row" id="row-back">
      <span class="motor-name">Back</span>
      <span class="motor-pwm" id="tval-back">0</span>
    </div>
  </div>
</div>

<pre id="raw-json">{}</pre>

<footer>Polling /cmd every 50 ms &middot; /stats every 500 ms</footer>

<script>
const MOTORS = ['front', 'left', 'right', 'back'];

function setMotor(name, pwm) {
  const circle = document.getElementById('m-' + name);
  const badge  = document.getElementById('pwm-' + name);
  const row    = document.getElementById('row-' + name);
  const tval   = document.getElementById('tval-' + name);

  badge.textContent = pwm;
  tval.textContent  = pwm;

  if (pwm > 0) {
    circle.classList.replace('inactive', 'active');
    row.classList.add('active-row');
  } else {
    circle.classList.replace('active', 'inactive');
    row.classList.remove('active-row');
  }
}

function timestamp() {
  return new Date().toLocaleTimeString('en-GB', {
    hour12: false, hour: '2-digit', minute: '2-digit',
    second: '2-digit', fractionalSecondDigits: 2
  });
}

async function pollCmd() {
  try {
    const data = await fetch('/cmd').then(r => r.json());

    MOTORS.forEach(m => setMotor(m, data[m] ?? 0));

    const anyActive = MOTORS.some(m => (data[m] ?? 0) > 0);
    const banner = document.getElementById('status-banner');
    if (anyActive) {
      banner.textContent = '\u26a0 Obstacle detected';
      banner.className   = 'active';
    } else {
      banner.textContent = 'No obstacle detected';
      banner.className   = 'safe';
    }

    document.getElementById('raw-json').textContent =
      JSON.stringify(data, null, 2);
    document.getElementById('card-updated').textContent = timestamp();
  } catch (_) {}
}

async function pollStats() {
  try {
    const data   = await fetch('/stats').then(r => r.json());
    const target = data.current_target;

    if (target && typeof target === 'object') {
      document.getElementById('card-target').textContent =
        target.class_name ?? '\u2014';
      document.getElementById('card-position').textContent =
        target.position   ?? '\u2014';
    } else if (typeof target === 'string' && target.length) {
      document.getElementById('card-target').textContent   = target;
      document.getElementById('card-position').textContent = '\u2014';
    } else {
      document.getElementById('card-target').textContent   = '\u2014';
      document.getElementById('card-position').textContent = '\u2014';
    }
  } catch (_) {}
}

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
    return HTMLResponse(content=_LIVE_HTML, status_code=200)
