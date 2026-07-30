import numpy as np

def get_object_depth(depth_map, bbox):
    x1, y1, x2, y2 = map(int, bbox)

    h, w = depth_map.shape

    x1 = max(0, min(x1, w - 1))
    x2 = max(0, min(x2, w - 1))
    y1 = max(0, min(y1, h - 1))
    y2 = max(0, min(y2, h - 1))

    if x2 <= x1 or y2 <= y1:
        return None

    box_width = x2 - x1
    box_height = y2 - y1

    # Lower-center region
    cx1 = x1 + int(box_width * 0.30)
    cx2 = x1 + int(box_width * 0.70)

    cy1 = y1 + int(box_height * 0.60)
    cy2 = y2

    crop = depth_map[cy1:cy2, cx1:cx2]

    if crop.size == 0:
        return None

    return float(np.median(crop))


def fuse_detections(detections, depth_map):
    fused = []

    for det in detections:
        fused.append({
            "label": det["label"],
            "confidence": det["confidence"],
            "bbox": det["bbox"],
            "depth": get_object_depth(depth_map, det["bbox"]),
        })

    return fused