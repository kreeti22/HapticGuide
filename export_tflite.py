"""
export_tflite.py
----------------
Exports YOLOv8n to TFLite fp32 via ONNX → onnx2tf on Windows.

Ultralytics 8.4+ dropped Windows support for direct LiteRT/TFLite export.
The workaround is the standard two-step path that works on all platforms:

  Step 1: PyTorch → ONNX     (via ultralytics, works everywhere)
  Step 2: ONNX   → TFLite    (via onnx2tf, works on Windows)

Run from the project root with the venv active:
    python export_tflite.py
"""

import os
import shutil
import sys

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PT_PATH     = os.path.join(SCRIPT_DIR, "backend", "yolov8n.pt")
ONNX_PATH   = os.path.join(SCRIPT_DIR, "yolov8n_export.onnx")   # temporary
ASSETS_DIR  = os.path.join(
    SCRIPT_DIR,
    "app", "hapticguide_app", "app", "src", "main", "assets"
)
TFLITE_DEST = os.path.join(ASSETS_DIR, "yolo_obstacle.tflite")
LABELS_DEST = os.path.join(ASSETS_DIR, "labels.txt")

os.makedirs(ASSETS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Step 1: PyTorch → ONNX
# ---------------------------------------------------------------------------
print("\n[1/5] Exporting YOLOv8n → ONNX (imgsz=320) ...")

from ultralytics import YOLO

model = YOLO(PT_PATH)
model.export(
    format="onnx",
    imgsz=320,
    dynamic=False,
    simplify=True,
    opset=12,      # opset 12 gives maximum onnx2tf compatibility
)

# Ultralytics saves the ONNX next to the .pt file
onnx_src = PT_PATH.replace(".pt", ".onnx")
if not os.path.exists(onnx_src):
    print(f"ERROR: expected ONNX at {onnx_src}")
    sys.exit(1)

shutil.copy2(onnx_src, ONNX_PATH)
print(f"    ONNX saved to: {ONNX_PATH}  ({os.path.getsize(ONNX_PATH)/1024:.1f} KB)")

# ---------------------------------------------------------------------------
# Step 2: ONNX → TFLite fp32 via onnx2tf
# ---------------------------------------------------------------------------
print("\n[2/5] Converting ONNX → TFLite fp32 via onnx2tf ...")

import onnx2tf

TFLITE_OUT_DIR = os.path.join(SCRIPT_DIR, "yolov8n_tflite_out")

onnx2tf.convert(
    input_onnx_file_path=ONNX_PATH,
    output_folder_path=TFLITE_OUT_DIR,
    output_tfv1_pb=False,
    output_h5=False,
    output_keras_v3=False,
    output_integer_quantized_tflite=False,
    output_dynamic_range_quantized_tflite=False,
    output_weights=False,
    copy_onnx_input_output_names_to_tflite=True,
    disable_strict_mode=True,  # avoids shape-inference errors on YOLO's dynamic shapes
)

print(f"    onnx2tf output dir: {TFLITE_OUT_DIR}")

# ---------------------------------------------------------------------------
# Step 3: Locate the fp32 .tflite file produced by onnx2tf
# ---------------------------------------------------------------------------
print("\n[3/5] Locating .tflite file ...")

def find_tflite(root: str) -> str | None:
    """
    Walk *root* and return the fp32 TFLite file.
    Preference: *_float32.tflite > any .tflite
    """
    fp32, any_tflite = [], []
    for dirpath, _, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".tflite"):
                full = os.path.join(dirpath, fn)
                any_tflite.append(full)
                if "float32" in fn:
                    fp32.append(full)
    return (fp32 or any_tflite or [None])[0]

tflite_src = find_tflite(TFLITE_OUT_DIR) or find_tflite(SCRIPT_DIR)

if tflite_src is None:
    print("ERROR: No .tflite file found after conversion.")
    sys.exit(1)

print(f"    Found: {tflite_src}")
print(f"    Size:  {os.path.getsize(tflite_src)/1024:.1f} KB")

# ---------------------------------------------------------------------------
# Step 4: Copy to assets/
# ---------------------------------------------------------------------------
print("\n[4/5] Copying to assets/ ...")

shutil.copy2(tflite_src, TFLITE_DEST)
print(f"    → {TFLITE_DEST}")

# ---------------------------------------------------------------------------
# Step 5: Write labels.txt — 80 COCO class names in index order
# ---------------------------------------------------------------------------
print("\n[5/5] Writing labels.txt ...")

COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane",
    "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird",
    "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat",
    "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut",
    "cake", "chair", "couch", "potted plant", "bed",
    "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven",
    "toaster", "sink", "refrigerator", "book", "clock",
    "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]

assert len(COCO_CLASSES) == 80

with open(LABELS_DEST, "w", encoding="utf-8") as f:
    f.write("\n".join(COCO_CLASSES) + "\n")

print(f"    → {LABELS_DEST}  ({len(COCO_CLASSES)} classes)")

# ---------------------------------------------------------------------------
# Cleanup temporary files
# ---------------------------------------------------------------------------
for tmp in [ONNX_PATH, onnx_src]:
    if os.path.exists(tmp):
        os.remove(tmp)
        print(f"    Cleaned up: {tmp}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
tflite_kb    = os.path.getsize(TFLITE_DEST) / 1024
labels_bytes = os.path.getsize(LABELS_DEST)

print("\n========================================")
print("  assets/ contents:")
for fn in sorted(os.listdir(ASSETS_DIR)):
    fp   = os.path.join(ASSETS_DIR, fn)
    size = os.path.getsize(fp)
    print(f"    {fn:<40} {size/1024:>8.1f} KB")
print("========================================")
print(f"  yolo_obstacle.tflite : {tflite_kb:.1f} KB")
print(f"  labels.txt           : {labels_bytes} bytes  (80 COCO classes)")
print("  Export complete.")
print("========================================\n")
