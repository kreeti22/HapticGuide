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
  background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
  min-height: 100vh;
  color: #e8eaf6;
  font-family: 'Segoe UI', 'Inter', system-ui, -apple-system, sans-serif;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 20px;
  gap: 28px;
  position: relative;
  overflow-x: hidden;
}

body::before {
  content: '';
  position: fixed;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background:
    radial-gradient(circle at 20% 30%, rgba(102, 126, 234, 0.15) 0%, transparent 50%),
    radial-gradient(circle at 80% 70%, rgba(118, 75, 162, 0.12) 0%, transparent 50%);
  pointer-events: none;
  z-index: 0;
}

h1 {
  font-size: 1.5rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: #fff;
  text-transform: uppercase;
  text-shadow: 0 2px 20px rgba(124, 92, 255, 0.5);
  z-index: 1;
}

/* ===== Glassmorphism Status Banner ===== */
#status-banner {
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  padding: 14px 36px;
  border-radius: 16px;
  text-align: center;
  min-width: 280px;
  transition: all 0.25s ease;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  z-index: 1;
}

#status-banner.safe {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.6);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

#status-banner.active {
  background: rgba(76, 175, 80, 0.12);
  border: 1px solid rgba(76, 175, 80, 0.35);
  color: #81c784;
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.3),
    inset 0 0 20px rgba(76, 175, 80, 0.08),
    0 0 30px rgba(76, 175, 80, 0.15);
  animation: pulse-glow 2s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3), inset 0 0 20px rgba(76, 175, 80, 0.08), 0 0 30px rgba(76, 175, 80, 0.15); }
  50% { box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3), inset 0 0 20px rgba(76, 175, 80, 0.12), 0 0 50px rgba(76, 175, 80, 0.25); }
}

/* ===== Curved Belt Container ===== */
.belt-wrapper {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.belt-label {
  font-size: 0.7rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.4);
}

.belt-container {
  position: relative;
  width: 360px;
  height: 220px;
}

/* The curved belt arc */
.belt-arc {
  position: absolute;
  top: 20px;
  left: 0;
  width: 360px;
  height: 200px;
  border-top-left-radius: 200px 200px;
  border-top-right-radius: 200px 200px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.1) 0%, rgba(255, 255, 255, 0.03) 100%);
  border: 2px solid rgba(255, 255, 255, 0.12);
  border-bottom: none;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  box-shadow:
    inset 0 2px 20px rgba(255, 255, 255, 0.05),
    0 10px 40px rgba(0, 0, 0, 0.3);
}

.belt-arc::before {
  content: '';
  position: absolute;
  top: 8px;
  left: 8px;
  right: 8px;
  height: calc(100% - 8px);
  border-top-left-radius: 192px 192px;
  border-top-right-radius: 192px 192px;
  border: 1.5px solid rgba(255, 255, 255, 0.08);
  border-bottom: none;
}

/* Belt buckle / center indicator */
.belt-center-line {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  width: 2px;
  height: 30px;
  background: linear-gradient(180deg, rgba(124, 92, 255, 0.8) 0%, transparent 100%);
  border-radius: 2px;
}

/* Motor node base styling */
.motor {
  position: absolute;
  width: 88px;
  height: 88px;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 700;
  transition: all 0.2s ease;
  user-select: none;
  z-index: 2;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.motor .motor-icon {
  font-size: 1.3rem;
  margin-bottom: 2px;
  line-height: 1;
}

.motor .pwm-val {
  font-size: 0.85rem;
  margin-top: 2px;
  font-weight: 700;
  font-family: 'Courier New', monospace;
}

/* Motor positions along the curved arc */
.motor.front {
  top: -20px;
  left: 50%;
  transform: translateX(-50%);
}

.motor.left {
  top: 85px;
  left: 0px;
  transform: rotate(-35deg);
}

.motor.left > * {
  transform: rotate(35deg);
}

.motor.right {
  top: 85px;
  right: 0px;
  transform: rotate(35deg);
}

.motor.right > * {
  transform: rotate(-35deg);
}

/* Inactive state */
.motor.inactive {
  background: rgba(255, 255, 255, 0.05);
  border: 2px solid rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.3);
  box-shadow: inset 0 2px 10px rgba(0, 0, 0, 0.2);
}
.motor.inactive .pwm-val { color: rgba(255, 255, 255, 0.2); }
.motor.inactive .motor-icon { opacity: 0.4; }

/* Active state */
.motor.active {
  background: rgba(76, 175, 80, 0.15);
  border: 2px solid rgba(129, 199, 132, 0.5);
  color: #a5d6a7;
  box-shadow:
    0 0 30px rgba(76, 175, 80, 0.4),
    0 0 60px rgba(76, 175, 80, 0.2),
    inset 0 0 20px rgba(76, 175, 80, 0.1);
  animation: motor-pulse 1.5s ease-in-out infinite;
}
.motor.active .pwm-val { color: #c8e6c9; }
.motor.active .motor-icon { color: #81c784; }

@keyframes motor-pulse {
  0%, 100% {
    box-shadow:
      0 0 30px rgba(76, 175, 80, 0.4),
      0 0 60px rgba(76, 175, 80, 0.2),
      inset 0 0 20px rgba(76, 175, 80, 0.1);
  }
  50% {
    box-shadow:
      0 0 45px rgba(76, 175, 80, 0.55),
      0 0 80px rgba(76, 175, 80, 0.3),
      inset 0 0 30px rgba(76, 175, 80, 0.15);
  }
}

/* Direction labels below belt */
.direction-labels {
  display: flex;
  justify-content: space-between;
  width: 360px;
  padding: 0 10px;
  margin-top: 8px;
}

.direction-labels span {
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.35);
  font-weight: 600;
}

.direction-labels .center-label {
  margin-right: 40px;
}

/* ===== Glassmorphism Cards ===== */
.cards {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  justify-content: center;
  max-width: 640px;
  width: 100%;
  z-index: 1;
}

.card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 18px;
  padding: 18px 22px;
  min-width: 170px;
  flex: 1;
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  transition: all 0.3s ease;
}

.card:hover {
  transform: translateY(-2px);
  border-color: rgba(124, 92, 255, 0.2);
  box-shadow:
    0 12px 40px rgba(0, 0, 0, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 0 30px rgba(124, 92, 255, 0.08);
}

.card .label {
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 8px;
  font-weight: 600;
}

.card .value {
  font-size: 1.05rem;
  color: #e8eaf6;
  word-break: break-all;
  font-weight: 500;
}

.card .value.highlight {
  color: #7c8cff;
  text-shadow: 0 0 20px rgba(124, 140, 255, 0.3);
}

/* ===== Glassmorphism PWM Table ===== */
.pwm-table {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 18px;
  padding: 18px 22px;
  min-width: 240px;
  flex: 1;
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.pwm-table .label {
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 14px;
  font-weight: 600;
}

.pwm-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.88rem;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.pwm-row:last-child { border-bottom: none; }
.pwm-row .motor-name { color: rgba(255, 255, 255, 0.6); font-weight: 500; }
.pwm-row .motor-pwm  {
  color: #e8eaf6;
  font-weight: 700;
  font-family: 'Courier New', monospace;
  background: rgba(255, 255, 255, 0.04);
  padding: 3px 10px;
  border-radius: 8px;
  min-width: 48px;
  text-align: right;
}
.pwm-row.active-row  .motor-name { color: #81c784; font-weight: 600; }
.pwm-row.active-row  .motor-pwm  {
  color: #a5d6a7;
  background: rgba(76, 175, 80, 0.12);
  border: 1px solid rgba(76, 175, 80, 0.2);
  box-shadow: 0 0 15px rgba(76, 175, 80, 0.1);
}

/* ===== Raw JSON Display ===== */
pre#raw-json {
  background: rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  padding: 18px 22px;
  font-size: 0.78rem;
  color: #80deea;
  max-width: 380px;
  width: 100%;
  overflow-x: auto;
  line-height: 1.7;
  z-index: 1;
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
}

footer {
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.3);
  letter-spacing: 0.08em;
  z-index: 1;
  font-weight: 500;
}

@media (max-width: 480px) {
  .belt-container, .direction-labels { width: 300px; }
  .belt-arc { width: 300px; height: 170px; }
  .motor { width: 72px; height: 72px; font-size: 0.6rem; }
  .motor.left, .motor.right { top: 70px; }
}
</style>
</head>
<body>

<h1>&#9889; HapticGuide &#8212; Live Belt Dashboard</h1>

<div id="status-banner" class="safe">No obstacle detected</div>

<!-- Curved Belt Visualisation -->
<div class="belt-wrapper">
  <div class="belt-label">Haptic Belt &#8212; Top View</div>
  <div class="belt-container">
    <div class="belt-arc"></div>
    <div class="belt-center-line"></div>

    <div id="m-left" class="motor left inactive">
      <div class="motor-icon">&#9664;</div>
      LEFT
      <span class="pwm-val" id="pwm-left">0</span>
    </div>

    <div id="m-front" class="motor front inactive">
      <div class="motor-icon">&#9650;</div>
      FRONT
      <span class="pwm-val" id="pwm-front">0</span>
    </div>

    <div id="m-right" class="motor right inactive">
      <div class="motor-icon">&#9654;</div>
      RIGHT
      <span class="pwm-val" id="pwm-right">0</span>
    </div>
  </div>
  <div class="direction-labels">
    <span>Left</span>
    <span class="center-label">Front</span>
    <span>Right</span>
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
    <div class="pwm-row" id="row-left">
      <span class="motor-name">Left</span>
      <span class="motor-pwm" id="tval-left">0</span>
    </div>
    <div class="pwm-row" id="row-front">
      <span class="motor-name">Front</span>
      <span class="motor-pwm" id="tval-front">0</span>
    </div>
    <div class="pwm-row" id="row-right">
      <span class="motor-name">Right</span>
      <span class="motor-pwm" id="tval-right">0</span>
    </div>
  </div>
</div>

<pre id="raw-json">{}</pre>

<footer>Polling /cmd every 50 ms &middot; /stats every 500 ms</footer>

<script>
const MOTORS = ['front', 'left', 'right'];

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
