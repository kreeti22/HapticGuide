import cv2
import torch
import numpy as np

from PIL import Image
from transformers import (
    AutoImageProcessor,
    AutoModelForDepthEstimation
)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

processor = AutoImageProcessor.from_pretrained(
    "depth-anything/Depth-Anything-V2-Small-hf"
)

model = AutoModelForDepthEstimation.from_pretrained(
    "depth-anything/Depth-Anything-V2-Small-hf"
).to(DEVICE)

model.eval()


def estimate_depth(frame):

    # OpenCV BGR -> RGB
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    image = Image.fromarray(rgb)

    inputs = processor(
        images=image,
        return_tensors="pt"
    ).to(DEVICE)

    with torch.no_grad():

        outputs = model(**inputs)

        predicted_depth = outputs.predicted_depth

    predicted_depth = torch.nn.functional.interpolate(
        predicted_depth.unsqueeze(1),
        size=image.size[::-1],
        mode="bicubic",
        align_corners=False,
    ).squeeze()

    depth = predicted_depth.cpu().numpy()

    return depth