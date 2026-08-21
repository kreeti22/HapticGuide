"""
test_detector_seg.py
--------------------
Targeted unit tests for YOLOv8 segmentation (YOLO-Seg) integration in HapticGuide.
"""

import sys
from pathlib import Path
import pytest
import numpy as np
import cv2

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from detector import YOLODetector, DetectedObject
from object_analyzer import ObjectAnalyzer, AnalyzedObject
from object_filter import ObjectFilter, ObstacleObject
from target_selector import TargetSelector, SelectedTarget
from tracker import ByteTracker, TrackedObject
from risk_estimator import RiskEstimator, RiskObject
from decision_engine import DecisionEngine


def test_yolo_seg_detector_initialization():
    """Verify YOLODetector initializes with YOLO-Seg model and task is 'segment'."""
    detector = YOLODetector()
    assert detector.model is not None
    assert getattr(detector.model, "task", None) == "segment"
    assert "person" in detector.model.names.values()


def test_yolo_seg_detector_empty_frame():
    """Verify detect() handles empty/None/blank frame gracefully."""
    detector = YOLODetector()
    assert detector.detect(None) == []
    assert detector.detect(np.zeros((0, 0, 3), dtype=np.uint8)) == []

    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    res = detector.detect(blank)
    assert isinstance(res, list)
    assert len(res) == 0


def test_yolo_seg_detector_segmentation_output():
    """Verify detect() on a sample image produces DetectedObject with segmentation data."""
    detector = YOLODetector()
    img_path = str(backend_dir / "looking-ahead.webp")
    img = cv2.imread(img_path)
    assert img is not None, f"Sample image {img_path} not found"

    detections = detector.detect(img)
    assert len(detections) > 0, "Expected at least one detection from sample image"

    for det in detections:
        assert isinstance(det, DetectedObject)
        assert isinstance(det.class_name, str)
        assert 0.0 <= det.confidence <= 1.0
        assert len(det.bbox) == 4
        assert det.bbox[0] < det.bbox[2]
        assert det.bbox[1] < det.bbox[3]
        assert det.width == det.bbox[2] - det.bbox[0]
        assert det.height == det.bbox[3] - det.bbox[1]
        assert det.area == det.width * det.height
        assert det.center_x == det.bbox[0] + det.width / 2.0
        assert det.center_y == det.bbox[1] + det.height / 2.0

        # Verify segmentation-specific fields
        if det.polygon is not None:
            assert isinstance(det.polygon, np.ndarray)
            assert det.polygon.ndim == 2
            assert det.polygon.shape[1] == 2
            assert det.mask_area is not None
            assert det.mask_area > 0


def test_downstream_pipeline_with_seg_detections():
    """Verify segmentation DetectedObjects flow through all downstream pipeline stages."""
    detector = YOLODetector()
    img_path = str(backend_dir / "looking-ahead.webp")
    img = cv2.imread(img_path)
    assert img is not None

    h, w = img.shape[:2]
    detections = detector.detect(img)
    assert len(detections) > 0

    # 1. ObjectAnalyzer
    analyzer = ObjectAnalyzer()
    analyzed = analyzer.analyze(detections, img_width=w)
    assert len(analyzed) == len(detections)
    assert isinstance(analyzed[0], AnalyzedObject)
    assert analyzed[0].position in ("LEFT", "CENTER", "RIGHT")

    # 2. TargetSelector
    selector = TargetSelector()
    target = selector.select(analyzed)
    assert target is not None
    assert isinstance(target, SelectedTarget)
    assert target.area > 0

    # 3. DecisionEngine
    decision_engine = DecisionEngine()
    cmd = decision_engine.compute_motor_command(target)
    assert isinstance(cmd, dict)
    assert set(cmd.keys()) == {"left", "front", "right", "back"}
    assert any(val > 0 for val in cmd.values())

    # 4. ObjectFilter
    obj_filter = ObjectFilter()
    filtered = obj_filter.filter(detections)
    assert len(filtered) > 0
    assert isinstance(filtered[0], ObstacleObject)

    # 5. ByteTracker
    tracker = ByteTracker()
    tracked = tracker.update(filtered)
    assert len(tracked) > 0
    assert isinstance(tracked[0], TrackedObject)
    assert tracked[0].id >= 1

    # 6. RiskEstimator
    risk_est = RiskEstimator()
    risks = risk_est.estimate_risk(tracked, frame_width=w, frame_height=h)
    assert len(risks) > 0
    assert isinstance(risks[0], RiskObject)
    assert 0.0 <= risks[0].risk_score <= 1.0


def test_segmentation_visualization_rendering():
    """Verify debug rendering processes segmentation mask overlays cleanly without bounding boxes."""
    from ai_worker import AIWorker

    worker = AIWorker()
    worker._show_debug_window = False

    img_path = str(backend_dir / "looking-ahead.webp")
    img = cv2.imread(img_path)
    assert img is not None

    detector = YOLODetector()
    analyzer = ObjectAnalyzer()
    selector = TargetSelector()
    decision_engine = DecisionEngine()

    detections = detector.detect(img)
    analyzed = analyzer.analyze(detections, img_width=img.shape[1])
    target = selector.select(analyzed)
    cmd = decision_engine.compute_motor_command(target)

    # Render debug frame (window display disabled in test)
    worker._render_debug_window(img, 10.0, analyzed, cmd, target)

