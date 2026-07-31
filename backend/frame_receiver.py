import asyncio
import cv2
import numpy as np

from fastapi import UploadFile

import globals


async def update_frame(image_file: UploadFile):
    """
    Accept a JPEG upload and decode it into an OpenCV BGR image.
    Replace any pending frame so the processor always works on the newest frame.
    """
    data = await image_file.read()
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Uploaded image could not be decoded")

    async with globals.frame_lock:
        globals.latest_frame["frame"] = frame

    globals.frame_event.set()
