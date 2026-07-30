from concurrent.futures import ThreadPoolExecutor
import json
import time

import cv2
import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from detector import detect
from depth import estimate_depth
from fusion import fuse_detections
from decision import prioritize_objects, generate_haptic_command


app = FastAPI()

# Two workers:
# 1 -> YOLO
# 2 -> Depth Anything
executor = ThreadPoolExecutor(max_workers=2)


def serialize_objects(objects):
    serialized = []

    for obj in objects:
        serialized.append({
            "label": obj["label"],
            "confidence": round(float(obj["confidence"]), 2),
            "bbox": [int(v) for v in obj["bbox"]],
            "depth": (
                round(float(obj["depth"]), 2)
                if obj["depth"] is not None
                else None
            ),
            "direction": obj["direction"],
            "priority": int(obj["priority"])
        })

    return serialized


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()

    print("Client Connected")

    last_print = time.time()

    try:

        while True:

            
            data = await websocket.receive_bytes()

            frame = cv2.imdecode(
                np.frombuffer(data, np.uint8),
                cv2.IMREAD_COLOR
            )

            if frame is None:
                continue

            start = time.perf_counter()

            yolo_future = executor.submit(detect, frame.copy())
            depth_future = executor.submit(estimate_depth, frame.copy())

            annotated_frame, detections = yolo_future.result()
            depth_map = depth_future.result()

            
            objects = fuse_detections(
                detections,
                depth_map
            )

     
            objects = prioritize_objects(
                objects,
                frame.shape[1]
            )

           
            haptic_command = generate_haptic_command(objects)

   
            payload = {
                "objects": serialize_objects(objects),
                "haptic": haptic_command
            }

            await websocket.send_text(
                json.dumps(payload)
            )
            elapsed = (
                time.perf_counter() - start
            ) * 1000

            if time.time() - last_print >= 1:

                print(f"Inference Time: {elapsed:.1f} ms")
    
                if objects:

                    for obj in objects:

                        print(
                            f"[P{obj['priority']}] "
                            f"{obj['label']} | "
                            f"{obj['direction']} | "
                            f"Depth={obj['depth']:.2f} | "
                            f"Conf={obj['confidence']:.2f}"
                        )

                    print("\nHaptic Command:")
                    print(haptic_command)

                else:

                    print("No objects detected.")

                last_print = time.time()

            cv2.imshow(
                "HapticGuide",
                annotated_frame
            )

            cv2.waitKey(1)

    except WebSocketDisconnect:

        print("❌ Client disconnected")

    finally:

        cv2.destroyAllWindows()