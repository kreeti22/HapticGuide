from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import cv2
import numpy as np
import time

from detector import detect

app = FastAPI()

last_print = time.time()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    global last_print

    await websocket.accept()

    print("Client Connected")

    try:

        while True:

            data = await websocket.receive_bytes()

            frame = cv2.imdecode(
                np.frombuffer(data, np.uint8),
                cv2.IMREAD_COLOR,
            )

            if frame is None:
                continue

            annotated, detections = detect(frame)

            if time.time() - last_print >= 1:

                if detections:

                    for obj in detections:
                        print(obj)

                else:
                    print("No objects detected.")


                last_print = time.time()

            cv2.imshow("HapticGuide", annotated)

            cv2.waitKey(1)

    except WebSocketDisconnect:
        print("Client disconnected")

    finally:
        cv2.destroyAllWindows()