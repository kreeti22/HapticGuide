import time
from concurrent.futures import ThreadPoolExecutor

import cv2
from detector import detect
from depth import estimate_depth
from fusion import fuse_detections
from decision import prioritize_objects, generate_haptic_command

# Keep the AI pipeline synchronous so process_frame(frame) stays unchanged.
# The async backend wraps this in a worker executor to avoid blocking the event loop.
executor = ThreadPoolExecutor(max_workers=2)
WINDOW_NAME = "HapticGuide"


def serialize_objects(objects):
    serialized = []
    for obj in objects:
        x1, y1, x2, y2 = obj["bbox"]
        serialized.append(
            {
                "label": obj["label"],
                "distance": round(float(obj["depth"]), 2) if obj["depth"] is not None else None,
                "x": int((x1 + x2) / 2),
                "y": int((y1 + y2) / 2),
            }
        )
    return serialized


def draw_annotations(frame, objects):
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    for obj in objects:
        x1, y1, x2, y2 = obj["bbox"]
        depth = obj["depth"]
        label = obj["label"]
        confidence = obj["confidence"]

        text = f"{label} {confidence:.2f}"
        depth_text = f"depth={depth:.2f}" if depth is not None else "depth=N/A"

        cv2.putText(
            frame,
            text,
            (x1, max(15, y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            depth_text,
            (x1, min(frame.shape[0] - 10, y2 + 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )

    cv2.imshow(WINDOW_NAME, frame)
    cv2.waitKey(1)


def process_frame(frame):
    """
    Process a BGR OpenCV frame through YOLO + Depth Anything + decision engine.

    This function is intentionally synchronous so it can be executed in a thread pool.
    """
    start = time.perf_counter()

    yolo_future = executor.submit(detect, frame.copy())
    depth_future = executor.submit(estimate_depth, frame.copy())

    annotated_frame, detections = yolo_future.result()
    depth_map = depth_future.result()

    objects = fuse_detections(detections, depth_map)
    objects = prioritize_objects(objects, frame.shape[1])
    haptic_command = generate_haptic_command(objects)

    draw_annotations(annotated_frame, objects)

    result = {
        "objects": serialize_objects(objects),
        "motor": {
            "left": int(haptic_command.get("left", 0)),
            "right": int(haptic_command.get("right", 0)),
            "front": int(haptic_command.get("center", 0)),
            "back": 0,
        },
        "raw": {
            "objects": objects,
            "haptic": haptic_command,
        },
        "processing_time_ms": round((time.perf_counter() - start) * 1000, 1),
    }

    return result
