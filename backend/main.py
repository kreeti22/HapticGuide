"""
main.py
-------
HapticGuide RTSP backend entry point.

Startup sequence
----------------
1. Print the HapticGuide banner.
2. Prompt the user for the phone IP and RTSP port.
3. Build rtsp://<IP>:<PORT>/live
4. Store the configured CameraStream in _STATE before uvicorn loads the module.
5. uvicorn imports main:app — the lifespan hook reads _STATE and calls .start().
6. On shutdown — lifespan calls .stop().

Why _STATE dict instead of a bare module-level variable
-------------------------------------------------------
When uvicorn is launched with `uvicorn.run("main:app", ...)` it imports the
module *after* __main__ has already assigned _STATE["stream"].
A bare `camera_stream: CameraStream` declaration at module level is None until
the assignment runs, and Python name resolution inside the lifespan coroutine
looks up the module-level name at *call time*, not at decoration time.

Storing the instance in a dict means the lifespan hook does:
    _STATE["stream"].start()
which reads from the dict at call time — always getting the value that was
placed there before uvicorn.run() was called.
"""

import os
import signal
import socket
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)
    else:
        load_dotenv()
except ImportError:
    pass

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from camera_stream import CameraStream
from shared_state import stop_event
from ai_worker import start_ai_worker, stop_ai_worker
from routes import router
from navigation.routes import router as navigation_router


# ---------------------------------------------------------------------------
# Module-level state container
# Populated by _collect_config() before uvicorn.run() is called.
# Read by the lifespan hook after uvicorn imports the module.
# ---------------------------------------------------------------------------

_STATE: dict = {
    "stream":     None,   # CameraStream instance — set before uvicorn starts
    "rtsp_url":   "",
}


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    print(
        "\n"
        "╔══════════════════════════════════════════╗\n"
        "║         HapticGuide AI Server            ║\n"
        "║         TCP Frame Receiver — v4.0        ║\n"
        "╚══════════════════════════════════════════╝\n",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _prompt_port() -> int:
    while True:
        try:
            raw = input("  Enter TCP Port  (default 9000): ").strip()
        except (EOFError, KeyboardInterrupt):
            return 9000
        if not raw:
            return 9000
        try:
            port = int(raw)
        except ValueError:
            print("  ✗  Please enter a number.", flush=True)
            continue
        if not (1 <= port <= 65535):
            print("  ✗  Port must be 1–65535.", flush=True)
            continue
        return port


def _prompt_show_window() -> bool:
    try:
        raw = input("  Show debug window? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return True
    return raw not in ("n", "no")


def _collect_config() -> None:
    """
    Run the interactive prompt, create the CameraStream TCP server,
    and store it in _STATE so the lifespan hook can reach it.
    """
    print("  ─────────────────────────────────────────", flush=True)
    port        = _prompt_port()
    show_window = _prompt_show_window()

    print(f"\n  TCP Port   : {port}", flush=True)
    print(f"  Debug win  : {'yes' if show_window else 'no'}", flush=True)
    print("  ─────────────────────────────────────────\n", flush=True)

    _STATE["rtsp_url"] = f"tcp://0.0.0.0:{port}"
    _STATE["stream"]   = CameraStream(
        tcp_port    = port,
        show_window = show_window,
    )


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    stream: CameraStream | None = _STATE.get("stream")

    if stream is None:
        raise RuntimeError(
            "CameraStream not initialised. "
            "Run 'python main.py' instead of invoking uvicorn directly."
        )

    print("[main] Starting camera stream and AI worker…", flush=True)
    stream.start()
    start_ai_worker()

    yield   # FastAPI is live

    # ── Shutdown ──────────────────────────────────────────────────────────────
    print("[main] Shutting down AI worker and camera stream…", flush=True)
    stop_ai_worker()
    stream.stop()
    print("[main] Shutdown complete.", flush=True)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title       = "HapticGuide",
    description = (
        "Read-only telemetry & motor command endpoint server. "
        "GET /cmd for motor outputs, GET /stats for performance metrics, GET /health for probes."
    ),
    version     = "4.0.0",
    lifespan    = lifespan,
)

app.include_router(router)
app.include_router(navigation_router)


# ---------------------------------------------------------------------------
# Port finder
# ---------------------------------------------------------------------------

def _find_free_port(preferred: int = 8000, search_range: int = 20) -> int:
    for p in range(preferred, preferred + search_range):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    raise RuntimeError(
        f"No free port in range {preferred}–{preferred + search_range - 1}."
    )


# ---------------------------------------------------------------------------
# Graceful Ctrl+C
# ---------------------------------------------------------------------------

def _install_signal_handler() -> None:
    original = signal.getsignal(signal.SIGINT)

    def _handler(sig, frame):
        print("\n[main] SIGINT — stopping…", flush=True)
        stop_event.set()
        if callable(original):
            original(sig, frame)

    signal.signal(signal.SIGINT, _handler)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _print_banner()

    try:
        _collect_config()           # fills _STATE["stream"] before uvicorn starts
    except (KeyboardInterrupt, EOFError):
        print("\n[main] Aborted.", flush=True)
        sys.exit(0)

    _install_signal_handler()

    preferred = int(os.getenv("PORT", 8000))
    http_port = _find_free_port(preferred)

    if http_port != preferred:
        print(
            f"[main] Port {preferred} busy — using {http_port}.",
            flush=True,
        )

    print(
        f"[main] HTTP server  →  http://0.0.0.0:{http_port}\n"
        f"[main] Endpoints    →  /cmd  /stats  /health  /nav/gps  /nav/search  /nav/route  /nav/voice  /nav/status\n"
        f"[main] TCP receiver →  {_STATE['rtsp_url']}\n",
        flush=True,
    )

    # Pass the app OBJECT, not the string "main:app".
    #
    # Passing a string causes uvicorn to re-import the "main" module in its
    # own import context. That second import creates a fresh _STATE dict with
    # stream=None, so the lifespan hook never sees the CameraStream we just
    # configured. Passing the object directly reuses this already-initialised
    # module — _STATE["stream"] is already set and lifespan finds it.
    #
    # Trade-off: passing the object disables uvicorn's --reload hot-reload
    # feature, which is fine — we don't use hot-reload in production.
    uvicorn.run(
        app,                    # ← object, not string
        host      = "0.0.0.0",
        port      = http_port,
        log_level = "warning",
    )
