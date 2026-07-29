from ultralytics import YOLO

# Load model only once
model = YOLO("yolov8n.pt")


def detect(frame):
    """
    Runs YOLO detection and returns:
    - annotated frame
    - detection list
    """

    results = model(frame, verbose=False)

    annotated = results[0].plot()

    detections = []

    for box in results[0].boxes:

        x1, y1, x2, y2 = box.xyxy[0].tolist()

        detections.append(
            {
                "label": model.names[int(box.cls[0])],
                "confidence": round(float(box.conf[0]), 2),
                "bbox": [
                    int(x1),
                    int(y1),
                    int(x2),
                    int(y2),
                ],
            }
        )

    return annotated, detections