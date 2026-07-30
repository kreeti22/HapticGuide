# HapticGuide

> **An AI-powered wearable navigation assistant for visually impaired users**

HapticGuide is a real-time assistive navigation system that uses computer vision to detect obstacles, estimate their relative distance, determine their direction, and convert this information into intuitive haptic feedback through a wearable belt.

The project combines **YOLOv8 object detection**, **Depth Anything V2**, **FastAPI**, **WebSockets**, and a custom decision engine to create a low-latency obstacle awareness system.

---

# Demo Pipeline

```
Camera
   │
   ▼
Browser (getUserMedia)
   │
   ▼
Canvas Capture
   │
   ▼
JPEG Compression
   │
   ▼
WebSocket Streaming
   │
   ▼
FastAPI Backend
   │
   ├───────────────┐
   ▼               ▼
YOLOv8n      Depth Anything V2
   │               │
   └───────┬───────┘
           ▼
 Object–Depth Fusion
           ▼
 Obstacle Decision Engine
           ▼
 Structured JSON
           ▼
 Browser Overlay
           ▼
 ESP32 Wearable (Upcoming)
```

---

# Features

### Computer Vision

* ✅ Real-time object detection (YOLOv8n)
* ✅ Monocular depth estimation (Depth Anything V2)
* ✅ Parallel inference using ThreadPoolExecutor
* ✅ GPU acceleration (CUDA)
* ✅ Object-depth fusion
* ✅ Relative distance estimation
* ✅ Structured obstacle representation

### Decision Engine

* ✅ Left / Center / Right localization
* ✅ Obstacle prioritization
* ✅ Closest obstacle selection
* ✅ Haptic command generation

### Frontend

* ✅ Browser camera streaming
* ✅ Live WebSocket communication
* ✅ Bounding-box visualization
* ✅ Depth display
* ✅ Direction display
* ✅ Priority display
* ✅ Browser overlay

### Upcoming

* 🚧 ESP32 communication
* 🚧 Wearable vibration belt
* 🚧 Navigation mode
* 🚧 Google Maps integration

---

# Architecture

```
                        Browser
             (HTML • CSS • JavaScript)
                       │
                getUserMedia()
                       │
                  JPEG Frames
                       │
                  WebSocket
                       │
                       ▼
               FastAPI Backend
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
      YOLOv8n              Depth Anything V2
         │                           │
         └─────────────┬─────────────┘
                       ▼
              Object–Depth Fusion
                       ▼
             Obstacle Decision Engine
                       ▼
           Left • Center • Right
                       ▼
            Haptic Command Generator
                       ▼
        JSON → Browser / ESP32 Belt
```

---

# Tech Stack

## Frontend

* HTML5
* CSS3
* JavaScript
* Canvas API
* WebSocket API
* getUserMedia()

## Backend

* FastAPI
* OpenCV
* NumPy
* WebSockets
* ThreadPoolExecutor
* PyTorch

## AI

* YOLOv8n (Ultralytics)
* Depth Anything V2 (Transformers)

---

# Project Structure

```
HapticGuide/

├── backend/
│   ├── app.py
│   ├── detector.py
│   ├── depth.py
│   ├── fusion.py
│   ├── decision.py
│   ├── requirements.txt
│   └── ...
│
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── script.js
│
└── README.md
```

---

# Development Progress

## Phase 1 — Camera Streaming

* [x] Browser camera access
* [x] Live preview
* [x] JPEG compression
* [x] WebSocket streaming
* [x] FastAPI receiver

---

## Phase 2 — Object Detection

* [x] YOLOv8n integration
* [x] GPU inference
* [x] Bounding boxes
* [x] Confidence extraction
* [x] Structured detections

Example

```json
{
    "label": "person",
    "confidence": 0.91,
    "bbox": [118, 74, 322, 468]
}
```

---

## Phase 3 — Depth Estimation

* [x] Depth Anything V2
* [x] Relative depth map
* [x] CUDA inference
* [x] NumPy depth output

Example

```
Depth Map

Shape : (407,612)

Min : -0.36

Max : 6.15
```

---

## Phase 4 — Object–Depth Fusion

* [x] Bounding-box alignment
* [x] Lower-center sampling
* [x] Median depth estimation
* [x] Per-object distance

Example

```json
{
    "label": "person",
    "confidence": 0.90,
    "depth": 4.63
}
```

---

## Phase 5 — Obstacle Decision Engine

* [x] Left / Center / Right partitioning
* [x] Priority ranking
* [x] Closest obstacle selection
* [x] Haptic command generation

Example

```json
{
    "label": "person",
    "direction": "center",
    "depth": 4.63,
    "priority": 1
}
```

Generated haptic payload

```json
{
    "left": 0,
    "center": 255,
    "right": 0
}
```

---

## Phase 6 — Browser Visualization

* [x] Live overlay
* [x] Bounding boxes
* [x] Depth labels
* [x] Direction labels
* [x] Priority labels
* [x] Live haptic status

---

## Phase 7 — ESP32 Wearable Belt

* [ ] WebSocket / Serial communication
* [ ] PWM motor driver
* [ ] Three vibration motors
* [ ] Distance-aware vibration intensity
* [ ] Wearable testing

---

## Phase 8 — Navigation

* [ ] Route planning
* [ ] Turn-by-turn navigation
* [ ] Obstacle-aware guidance
* [ ] Outdoor testing

---

# Example Backend Response

```json
{
  "objects": [
    {
      "label": "person",
      "confidence": 0.91,
      "bbox": [120, 80, 330, 470],
      "depth": 4.63,
      "direction": "center",
      "priority": 1
    }
  ],
  "haptic": {
    "left": 0,
    "center": 255,
    "right": 0
  }
}
```

---

# Current Status

✅ Browser camera streaming

✅ Real-time WebSocket communication

✅ Parallel AI inference

✅ YOLOv8 object detection

✅ Depth Anything V2

✅ Object-depth fusion

✅ Obstacle prioritization

✅ Browser visualization overlay

🚧 ESP32 wearable integration

🚧 Navigation system

---

# Roadmap

```
Camera
   │
   ▼
YOLOv8 Detection
   │
   ▼
Depth Anything V2
   │
   ▼
Object–Depth Fusion
   │
   ▼
Decision Engine
   │
   ▼
Browser Overlay
   │
   ▼
ESP32 Wearable Belt
   │
   ▼
Navigation Mode
   │
   ▼
Real-Time Assistance
```

---

# Vision

HapticGuide aims to provide visually impaired users with an affordable, real-time navigation assistant by combining modern computer vision with intuitive haptic feedback. The long-term goal is a lightweight wearable capable of obstacle avoidance and navigation without requiring specialized cameras or expensive hardware.
