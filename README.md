# HapticGuide
AI-powered wearable navigation assistant for visually impaired users

HapticGuide is a real-time computer vision system that detects obstacles using a camera and converts them into haptic feedback through a wearable belt. The long-term goal is to provide safe navigation by combining object detection, depth estimation, and navigation guidance.

## Project Status

Current Progress: Phase 1 & 2 Complete

Camera Stream
│
▼
WebSocket Streaming
│
▼
FastAPI Backend
│
▼
YOLOv8n Detection
│
▼
Bounding Boxes + Detection JSON


*Depth estimation, obstacle fusion, navigation, and ESP32 integration are planned in upcoming phases.*

---

## Vision & Architecture

The system consists of three major components:
1. **Web Client**: Captures camera frames and streams them to the backend.
2. **AI Backend**: Detects surrounding objects, estimates obstacle distance, and determines obstacle priority.
3. **Wearable Belt**: Receives obstacle information and generates directional haptic feedback.

Browser (getUserMedia -> Canvas -> JPEG Compression -> WebSocket)
│
▼
FastAPI Backend (Frame Decoder -> YOLOv8n -> Detection Pipeline -> OpenCV Visualization)


---

## Tech Stack & Structure

- **Frontend**: HTML, CSS, JavaScript, WebSocket API, `getUserMedia()`, Canvas API
- **Backend**: FastAPI, OpenCV, NumPy, WebSockets, Ultralytics YOLOv8

HapticGuide/
├── backend/
│   ├── app.py
│   ├── detector.py
│   └── requirements.txt
└── frontend/
├── index.html
└── script.js


---

## Development Task Tracker

### Phase 1: Camera Streaming
- [x] Implement browser camera access (`getUserMedia`)
- [x] Set up live video preview canvas
- [x] Implement canvas frame capture & JPEG compression
- [x] Establish WebSocket streaming client-side
- [x] Create FastAPI WebSocket server endpoint
- [x] Implement frame decoding pipeline using OpenCV

### Phase 2: Real-Time Object Detection
- [x] Integrate Ultralytics YOLOv8n model
- [x] Build automatic model loading & initialization system
- [x] Implement real-time frame inference loop
- [x] Render bounding box visualization on frames
- [x] Extract confidence scores and object labels
- [x] Build structured JSON detection serializer

#### Sample Detection Output Schema
```json
[
  {
    "label": "person",
    "confidence": 0.92,
    "bbox": [120, 88, 605, 479]
  },
  {
    "label": "chair",
    "confidence": 0.81,
    "bbox": [15, 210, 164, 472]
  }
]
```
Phase 3: Monocular Depth Estimation
[ ] Evaluate candidate models (Depth Anything V2 vs Metric3D)

[ ] Integrate depth estimation pipeline into backend

[ ] Calculate per-frame pixel depth maps

[ ] Output per-object distance estimation ({"label": "person", "distance": 1.42})

Phase 4: Object-Depth Fusion
[ ] Align 2D bounding boxes with monocular depth maps

[ ] Calculate bounding-box spatial mean depth

[ ] Implement object-specific distance calculation engine

Phase 5: Obstacle Decision Engine
[ ] Implement directional spatial grid partitioning (Left, Center, Right)

[ ] Calculate relative obstacle danger levels based on distance & velocity

[ ] Determine primary high-priority collision threat

Phase 6: Navigation System
[ ] Integrate external route planning & navigation API

[ ] Implement turn-by-turn instruction handler

[ ] Convert route maneuvers into spatial haptic guidance signals

Phase 7: ESP32 Wearable Belt Integration
[ ] Establish communication channel between backend and ESP32

[ ] Define directional vibration intensity payload format (e.g., {"left": 0, "center": 255, "right": 0})

[ ] Implement PWM driver code on ESP32 for haptic motor control

[ ] End-to-end wearable system integration test

Master Pipeline Roadmap
Camera
  │
  ▼
Object Detection (YOLOv8n) [Done]
  │
  ▼
Depth Estimation [In Progress]
  │
  ▼
Object + Depth Fusion [Planned]
  │
  ▼
Obstacle Classification [Planned]
  │
  ▼
Navigation Logic [Planned]
  │
  ▼
ESP32 Haptic Belt [Planned]
  │
  ▼
Directional Vibration Feedback [Planned]
