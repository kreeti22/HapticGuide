import asyncio
import json

from aiortc import MediaStreamTrack
from aiortc.contrib.media import MediaBlackhole

from ai_pipeline import process_frame


async def consume_video(track: MediaStreamTrack, data_channel):
    """
    Continuously receive frames from the incoming WebRTC video track,
    process each frame with process_frame(frame), and forward the result
    over the WebRTC data channel.
    """
    try:
        while True:
            frame = await track.recv()
            image = frame.to_ndarray(format="bgr24")
            result = await asyncio.get_running_loop().run_in_executor(
                None, process_frame, image
            )
            if data_channel and data_channel.readyState == "open":
                data_channel.send(json.dumps({"type": "ai_result", "payload": result}))
    except Exception:
        await track.stop()
