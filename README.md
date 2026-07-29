# HapticGuide

> **AI-powered wearable navigation assistant for visually impaired users**

HapticGuide is a real-time computer vision system that detects obstacles using a camera and converts them into directional haptic feedback through a wearable belt. The system combines object detection, monocular depth estimation, obstacle fusion, and navigation logic to help users safely navigate their surroundings.

---

# Current Status

**Phase 1–4 Complete**

```
Camera
   │
   ▼
Browser (getUserMedia)
   │
   ▼
Canvas → JPEG Compression
   │
   ▼
WebSocket Streaming
   │
   ▼
FastAPI Backend
   │
   ├──────────────┐
   ▼              ▼
YOLOv8n      Depth Anything V2
   │              │
   └──────┬───────┘
          ▼
 Object-Depth Fusion
          ▼
 Structured Obstacle JSON
```

---

# Features

- ✅ Real-time browser camera streaming
- ✅ WebSocket communication
- ✅ FastAPI backend
- ✅ YOLOv8n object detection
- ✅ Depth Anything V2 (Hugging Face Transformers)
- ✅ Object-depth fusion
- ✅ Per-object relative depth estimation
- ✅ Structured obstacle output
- 🚧 Navigation logic (In Progress)
- 🚧 ESP32 wearable integration (Upcoming)

---

# Architecture

```
┌──────────────────────┐
│      Web Client      │
│  HTML + JavaScript   │
│  getUserMedia()      │
└──────────┬───────────┘
           │
           ▼
     JPEG Frames
           │
           ▼
      WebSocket
           │
           ▼
┌─────────────────────────────┐
│       FastAPI Backend       │
│                             │
│   Frame Decoder             │
│          │                  │
│          ▼                  │
│  ┌──────────────┐           │
│  │ YOLOv8n      │           │
│  └──────────────┘           │
│          │                  │
│  ┌──────────────┐           │
│  │ DepthAnything│           │
│  └──────────────┘           │
│          │                  │
│          ▼                  │
│   Object-Depth Fusion       │
│          │                  │
│          ▼                  │
│   Obstacle Decision Engine  │
└──────────┬──────────────────┘
           │
           ▼
      ESP32 Controller
           │
           ▼
   Wearable Haptic Belt
```

---

# Tech Stack

## Frontend

- HTML5
- CSS3
- JavaScript
- Canvas API
- WebSocket API
- getUserMedia()

## Backend

- FastAPI
- OpenCV
- NumPy
- WebSockets
- Ultralytics YOLOv8
- Hugging Face Transformers
- PyTorch

## AI Models

- YOLOv8n
- Depth Anything V2 Small

---

# Project Structure

```
HapticGuide/

├── backend/
│   ├── app.py
│   ├── detector.py
│   ├── depth.py
│   ├── fusion.py
│   ├── test.py
│   └── requirements.txt
│
└── frontend/
    ├── index.html
    └── script.js
```

---

# Development Progress

## Phase 1 — Camera Streaming 

- [x] Browser camera access (`getUserMedia`)
- [x] Live video preview
- [x] Canvas frame capture
- [x] JPEG compression
- [x] WebSocket streaming
- [x] FastAPI WebSocket server
- [x] OpenCV frame decoding

---

## Phase 2 — Real-Time Object Detection 

- [x] YOLOv8n integration
- [x] Automatic model loading
- [x] Real-time inference
- [x] Bounding box visualization
- [x] Confidence extraction
- [x] Structured detection JSON

Example:

```json
{
    "label": "person",
    "confidence": 0.91,
    "bbox": [120, 80, 330, 470]
}
```

---

## Phase 3 — Monocular Depth Estimation 

- [x] Integrated Depth Anything V2
- [x] Hugging Face Transformers implementation
- [x] GPU acceleration (CUDA)
- [x] Relative depth map generation
- [x] NumPy depth map output

Example:

```
Depth Map

Shape: (407, 612)
Min: -0.36
Max: 6.15
```

---

## Phase 4 — Object-Depth Fusion 

- [x] Bounding-box alignment
- [x] Lower-center depth sampling
- [x] Median depth estimation
- [x] Object-wise depth calculation

Example Output

```json
{
    "label": "person",
    "confidence": 0.87,
    "bbox": [363, 86, 441, 273],
    "depth": 2.11
}
```

---

## Phase 5 — Obstacle Decision Engine 

- [ ] Left / Center / Right spatial partitioning
- [ ] Obstacle priority ranking
- [ ] Collision risk estimation
- [ ] Closest obstacle selection

Target Output

```json
{
    "label": "person",
    "direction": "center",
    "depth": 2.11,
    "priority": 1
}
```

---

## Phase 6 — Navigation System 

- [ ] Route planning integration
- [ ] Turn-by-turn instruction parsing
- [ ] Navigation-aware obstacle handling
- [ ] Smart vibration guidance

---

## Phase 7 — ESP32 Wearable Belt 

- [ ] Backend → ESP32 communication
- [ ] Vibration payload protocol
- [ ] PWM motor driver
- [ ] Multi-motor haptic feedback
- [ ] End-to-end wearable testing

Example Payload

```json
{
    "left": 0,
    "center": 255,
    "right": 0
}
```

---

# Roadmap

```
Camera
    │
    ▼
YOLOv8n Detection
    │
    ▼
Depth Anything V2
    │
    ▼
Object-Depth Fusion
    │
    ▼
Obstacle Decision Engine
    │
    ▼
Navigation Logic
    │
    ▼
ESP32 Controller
    │
    ▼
Wearable Haptic Belt
    │
    ▼
Real-Time Navigation Assistance
```

---

# Current Milestone

Browser-based live camera streaming

Real-time YOLOv8 object detection

Monocular depth estimation

Object-depth fusion

Obstacle prioritization

Wearable haptic navigation