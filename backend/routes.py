import asyncio
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

from frame_receiver import update_frame
from globals import latest_command

router = APIRouter()


@router.post("/receive")
async def receive_frame(image: UploadFile = File(...)):
    """
    Receive a single JPEG image via multipart/form-data, decode it,
    and schedule it for async processing by the frame worker.
    """
    if image.content_type not in ("image/jpeg", "image/jpg"):
        raise HTTPException(status_code=400, detail="Only JPEG images are supported")

    try:
        await update_frame(image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return JSONResponse({"status": "accepted"})


@router.get("/send")
async def send_command():
    """
    Return the latest stored motor command and object list.
    This endpoint does not perform inference.
    """
    return latest_command
