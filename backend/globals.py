# Global state storage for the HTTP frame transport.
# latest_command is returned by GET /send and updated after each processed frame.

latest_command = {
    "left": 0,
    "right": 0,
    "front": 0,
    "back": 0,
    "objects": [],
}

# latest_frame holds the most recent JPEG-decoded OpenCV image.
# If a newer frame arrives while processing, it replaces the old one.
latest_frame = None

# The event is used to wake the processor when a new frame arrives.
frame_event = None

# A lock synchronizes access to latest_frame.
frame_lock = None
