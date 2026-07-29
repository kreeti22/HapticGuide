from navigation import get_direction

def fuse_detections(detections, depth_map):
    h, w = depth_map.shape

    fused = []

    for det in detections:

        fused.append({
            "label": det["label"],
            "confidence": det["confidence"],
            "bbox": det["bbox"],
            "depth": get_object_depth(depth_map, det["bbox"]),
            "direction": get_direction(det["bbox"], w)
        })

    return fused