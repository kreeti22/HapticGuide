import cv2

from detector import detect
from depth import estimate_depth
from fusion import fuse_detections

img = cv2.imread("looking-ahead.webp")

_, detections = detect(img)

depth_map = estimate_depth(img)

objects = fuse_detections(detections, depth_map)

print()

for obj in objects:
    print(obj)