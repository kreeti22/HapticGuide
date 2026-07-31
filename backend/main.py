import asyncio
import os
from socket import socket

import uvicorn
from fastapi import FastAPI

import globals
from ai_pipeline import process_frame
from routes import router

app = FastAPI(title="HapticGuide HTTP Transport")
app.include_router(router)


def get_available_port(default_port=8000):
    requested_port = int(os.getenv("PORT", default_port))
    with socket() as sock:
        try:
            sock.bind(("0.0.0.0", requested_port))
            return requested_port
        except OSError:
            pass

    for candidate in range(requested_port + 1, requested_port + 20):
        with socket() as sock:
            try:
                sock.bind(("0.0.0.0", candidate))
                return candidate
            except OSError:
                continue

    raise RuntimeError("No free port available")


async def frame_worker():
    """
    Background worker that processes the newest available frame.
    If multiple frames arrive while processing, only the latest frame is kept.
    """
    while True:
        await globals.frame_event.wait()
        globals.frame_event.clear()

        async with globals.frame_lock:
            frame = globals.latest_frame.get("frame")
            globals.latest_frame["frame"] = None

        if frame is None:
            continue

        result = await asyncio.get_running_loop().run_in_executor(
            None, process_frame, frame
        )

        globals.latest_command.clear()
        globals.latest_command.update(result)


@app.on_event("startup")
async def startup_event():
    globals.frame_event = asyncio.Event()
    globals.frame_lock = asyncio.Lock()
    globals.latest_frame = {"frame": None}
    asyncio.create_task(frame_worker())


if __name__ == "__main__":
    port = get_available_port()
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
