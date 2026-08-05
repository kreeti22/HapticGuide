# HapticGuide: AI-Powered Wearable Haptic Navigation System

> **Comprehensive Technical Documentation & System Specification**  
> *HapticGuide is an open, real-time, low-latency assistive navigation system for visually impaired individuals, pairing smartphone computer vision with an ESP32 haptic vibration belt.*

---

## Table of Contents
- [Project Overview](#project-overview)
- [Motivation](#motivation)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [AI Pipeline](#ai-pipeline)
- [Hardware](#hardware)
- [Software Stack](#software-stack)
- [Communication Architecture](#communication-architecture)
- [Repository Structure](#repository-structure)
- [Current Workflow](#current-workflow)
- [Performance](#performance)
- [Challenges Faced](#challenges-faced)
- [Future Roadmap](#future-roadmap)
- [How to Run](#how-to-run)
- [Demo](#demo)
- [Contributors](#contributors)
- [License](#license)

---

# Project Overview

### What HapticGuide Is
**HapticGuide** is an intelligent, real-time wearable navigation assistant designed to aid visually impaired and blind individuals in navigating physical environments safely. It captures live camera frames via a smartphone camera, streams them over a ultra-low-latency raw TCP socket connection to a high-performance Python computer vision backend, processes the visual data using deep learning models (YOLOv8) and specialized spatial reasoning modules, and converts spatial obstacle information into intuitive, multi-directional tactile vibrations on an ESP32-powered haptic belt worn around the waist.

### The Real-World Problem It Solves
Globally, over 2.2 billion people suffer from vision impairments. Traditional navigation aids—such as white canes—only detect obstacles at ground level within arm's reach and provide zero spatial feedback regarding head-height hazards, approaching objects, or directional obstacle geometry. Modern digital solutions often rely on intrusive audio cues (beeps, synthesized speech) that block the user's critical auditory senses, isolating them from ambient environmental sounds necessary for safety.

HapticGuide addresses these core challenges by:
1. **Providing Hands-Free Spatial Awareness**: Continuously scanning the environment for high-priority obstacles (people, vehicles, furniture, doors).
2. **Silent Tactile Sensing**: Translating spatial obstacle locations (Left, Front/Center, Right, Back) into localized vibrations, leaving auditory channels completely free.
3. **Sub-100ms End-to-End Latency**: Giving users real-time feedback while moving at normal walking speeds.

### Why It Is Different
Unlike existing commercial or academic assistive solutions, HapticGuide avoids costly hardware while maximizing situational feedback:

| Feature / Aspect | White Cane | Smart Glasses (e.g. Envision / OrCam) | HapticGuide |
| :--- | :--- | :--- | :--- |
| **Cost** | Low ($20–$50) | Extremely High ($2,000–$4,000+) | Low ($30 for ESP32/belt + user's phone) |
| **Detection Scope** | Ground-level touch only | Text/Face reading; limited spatial guidance | Full 3D spatial field & directional hazards |
| **Feedback Channel** | Tactile (mechanical cane feedback) | Auditory (Speech/Chimes) — blocks ears | Silent Multi-Directional Haptic Belt |
| **Head-Height Hazards** | Cannot detect | Partial detection | Full detection via smartphone field-of-view |
| **Hardware Overhead** | Simple stick | Heavy, battery-constrained glasses | Offloads heavy computation to edge/cloud backend |

### Target Users
- **Blind & Visually Impaired Individuals**: Seeking an unobtrusive, hands-free secondary navigation aid for indoor and outdoor mobility.
- **Orientation & Mobility (O&M) Specialists**: Looking for open-source assistive tools for client training.
- **Robotics & Assistive Technology Researchers**: Seeking a modular platform for spatial AI, edge processing, and human-computer interaction (HCI).

---

# Motivation

### Why This Project Was Built
Visual independence is a fundamental component of mobility, safety, and personal dignity. Navigating unknown environments—such as busy urban streets, unfamiliar indoor corridors, or dynamic office settings—presents constant physical risks and mental strain for visually impaired individuals. Most state-of-the-art vision solutions either treat spatial perception as an auditory reading exercise or lock features behind expensive proprietary hardware. 

HapticGuide was created to democratize spatial computer vision by repurposing everyday hardware (smartphones, low-cost microcontrollers, motor drivers) into an intuitive "second sense."

### Emotional and Practical Impact
- **Restoring Environmental Confidence**: Users can walk naturally without constant fear of walking into unexpected obstacles, wall corners, or overhanging objects.
- **Preserving Hearing**: By using tactile feedback rather than audio prompts, users retain 100% awareness of environmental acoustics (traffic noise, footsteps, voices).
- **Subconscious Navigation**: Spatial vibration mapping (vibration on the left side means obstacle on the left) aligns with human neurobiology, enabling users to react reflexively within fractions of a second.

---

# Key Features

### Implemented Features

#### 1. Real-Time Obstacle Detection
- Continuous single-pass image processing pipeline capable of detecting dynamic and static obstacles in real time.
- Identifies humans, furniture, vehicles, doors, steps, and general structural hazards.

#### 2. Raw TCP Low-Latency Camera Streaming
- Replaced standard HTTP/REST frame uploads with a dedicated, custom binary TCP protocol on port 9000.
- Incorporates `TCP_NODELAY` (disabling Nagle's algorithm) and zero-copy memoryview buffers to minimize frame transport overhead.
- Features a drop-oldest single-slot buffer (`_RawJpegSlot`) guaranteeing that the AI pipeline always consumes the freshest available frame with zero queue buildup.

#### 3. YOLO Object Detection (`YOLODetector`)
- Powered by `YOLOv8n` (Ultralytics), executing GPU/CUDA-accelerated inference in FP16 precision.
- Returns bounding box coordinates `[x1, y1, x2, y2]`, detection confidence scores, bounding box areas, and spatial centroids (`center_x`, `center_y`).

#### 4. Object Analyzer (`ObjectAnalyzer`)
- Enriches raw YOLO detections with spatial and semantic metadata:
  - **Horizontal Position**: Maps object centroid `center_x` into discrete spatial regions (`LEFT`, `CENTER`, `RIGHT`).
  - **Class Priority**: Assigns class-based risk scores using a customizable `PRIORITY_TABLE` (e.g., vehicles and people prioritized higher than small static items).

#### 5. Target Selector (`TargetSelector`)
- Evaluates enriched `AnalyzedObject` candidates and isolates a single high-priority `SelectedTarget`.
- Implements deterministic selection logic (e.g., largest bounding box area indicating closest proximity) while logging exact selection justifications.

#### 6. Decision Engine (`DecisionEngine`)
- Translates the isolated `SelectedTarget` into discrete PWM motor control signals.
- Maps spatial orientation (`LEFT` $\rightarrow$ Left Motor, `CENTER` $\rightarrow$ Front Motor, `RIGHT` $\rightarrow$ Right Motor, `BACK` $\rightarrow$ Back Motor).
- Updates global motor state (`globals.latest_command`) under thread locks for instantaneous retrieval.

#### 7. Live Debugging Dashboard & Web Interface
- Provides a real-time web interface powered by WebSockets, rendering live camera feeds with overlaid color-coded bounding boxes, class labels, spatial positions, and motor output status.
- Includes a dedicated terminal telemetry output streaming network FPS, AI FPS, frame decoding time, and latency metrics every second.

#### 8. ESP32 Haptic Feedback Firmware
- Built on the Arduino / ESP-IDF framework for ESP32 microcontrollers.
- Connects to local Wi-Fi and polls the backend `/command` endpoint over HTTP with active keep-alive socket persistence.
- Drives 4 independent vibration motor channels via 8-bit LEDC PWM channels (5 kHz PWM frequency).
- Includes fail-safe protection: automatically shuts off all motors (PWM 0) if Wi-Fi or backend communication drops for >150 ms.

#### 9. Four-Direction Vibration Guidance
- Physical motor array mapped to 4 cardinal directions: Left, Front (Center), Right, and Back.
- Provides immediate tactile feedback corresponding directly to the direction of impending hazards.

---

### Planned Features

- 🚧 **Monocular Depth Fusion (Depth Anything V2 Integration)**: Merging YOLO bounding boxes with monocular depth maps to calculate precise metric distances ($d_{meters}$) rather than bounding-box proxy areas.
- 🚧 **Multi-Object Distance-Aware PWM Scaling**: Dynamically modulating motor vibration intensity ($0 \text{ to } 255$) proportional to object proximity and closing speed.
- 🚧 **ByteTrack / DeepSORT Object Tracking**: Adding persistent object IDs across frames to estimate trajectory vectors and collision risks.
- 🚧 **Voice Command & Audio Alerts**: Optional Bluetooth earbud integration for non-critical turn-by-turn guidance or object identity queries ("What's ahead?").
- 🚧 **Turn-by-Turn GPS & Indoor Navigation**: Integrating Google Maps API and visual-inertial odometry for destination routing.

---

# System Architecture

### Data Flow Overview

```
Android Camera
      │
Raw TCP Streaming (Port 9000, Header + JPEG Payload)
      │
Backend (camera_stream.py TCP Receiver Thread)
      │
YOLO (YOLODetector / FP16 GPU Inference)
      │
Object Analyzer (Spatial Partitioning & Priority Lookup)
      │
Target Selector (Target Isolation by Proximity/Area)
      │
Decision Engine (Haptic Axis Mapping & State Mutex)
      │
FastAPI (Uvicorn HTTP Endpoint GET /command)
      │
ESP32 (Wi-Fi Poller & LEDC PWM Driver)
      │
Motor Drivers (Transistor / MOSFET / H-Bridge Driver Board)
      │
Vibration Motors (4x Haptic Motors: Left, Front, Right, Back)
```

### Stage Responsibilities

1. **Android Camera**: Captures live video feed (YUV420 format), resizes/compresses to 416x416 JPEG frames using Android CameraX API.
2. **Raw TCP Streaming**: Sends binary packet stream (4-byte length header + 8-byte timestamp + raw JPEG bytes) over socket connection with `TCP_NODELAY` enabled.
3. **Backend TCP Receiver**: Listens on TCP port 9000, reads packets directly into pre-allocated memory buffers, and updates a single-slot drop-oldest buffer slot.
4. **YOLO Detection**: Decodes JPEG payload using OpenCV, passes frame to YOLOv8n running on GPU/CUDA, and extracts bounding boxes, confidences, and labels.
5. **Object Analyzer**: Partitions frame horizontally into 3 equal columns (`LEFT` $< 33\%$, `CENTER` $33\%-66\%$, `RIGHT` $> 66\%$), computes object centroids, and attaches priority scores.
6. **Target Selector**: Evaluates all detected objects and selects the single most critical obstacle based on spatial area and class priority.
7. **Decision Engine**: Converts selected target position into a 4-channel motor dictionary `{"left": int, "front": int, "right": int, "back": int}` and writes atomically to shared memory (`globals.latest_command`).
8. **FastAPI Server**: Exposes asynchronous REST endpoints (`GET /command`, `GET /stats`, `POST /receive`) for microcontrollers and web frontends.
9. **ESP32 Microcontroller**: Polls `GET /command` every 30–40 ms over local Wi-Fi, parsing JSON payload using `ArduinoJson`.
10. **Motor Drivers**: Converts low-current ESP32 GPIO PWM signals (3.3V) to high-current motor drive signals (5V/3.7V).
11. **Vibration Motors**: Eccentric Rotating Mass (ERM) or Linear Resonant Actuator (LRA) haptic motors vibrate on the user's belt corresponding to obstacle position.

---

# AI Pipeline

The AI Pipeline is designed as a modular, decoupled processing chain where each component has distinct inputs, outputs, and responsibilities.

```
+-------------------------------------------------------------------------+
|                              INPUT FRAME                                |
|                        (BGR Image, 416x416 NumPy)                       |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                              YOLODetector                               |
|  - Runs YOLOv8n FP16 CUDA Inference                                    |
|  - Filters by confidence threshold (default 0.25)                      |
+-------------------------------------------------------------------------+
                                     |
                                     v
                           List[DetectedObject]
                                     |
                                     v
+-------------------------------------------------------------------------+
|                             ObjectAnalyzer                              |
|  - Calculates spatial position (LEFT, CENTER, RIGHT)                   |
|  - Queries PRIORITY_TABLE for class-specific priority score             |
+-------------------------------------------------------------------------+
                                     |
                                     v
                           List[AnalyzedObject]
                                     |
                                     v
+-------------------------------------------------------------------------+
|                             TargetSelector                              |
|  - Selects single highest risk target (Rule V1: Max Area)               |
|  - Attaches human-readable selection reason                             |
+-------------------------------------------------------------------------+
                                     |
                                     v
                         Optional[SelectedTarget]
                                     |
                                     v
+-------------------------------------------------------------------------+
|                             DecisionEngine                              |
|  - Maps target position to discrete motor channel                       |
|  - Atomically updates globals.latest_command under thread lock          |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                            MOTOR COMMAND                                |
|          {"left": 0, "front": 255, "right": 0, "back": 0}              |
+-------------------------------------------------------------------------+
```

### Module Breakdown

#### 1. `YOLODetector` (`detector.py`)
- **Responsibility**: Performs deep learning object detection on input camera frames. Loads model weights once during startup to eliminate execution overhead.
- **Inputs**: BGR image (`np.ndarray`, shape `(H, W, 3)`).
- **Outputs**: `List[DetectedObject]`, where each `DetectedObject` contains:
  - `class_name` (`str`): Detected COCO class label (e.g. `"person"`, `"chair"`).
  - `confidence` (`float`): Detection probability ($0.0 - 1.0$).
  - `bbox` (`List[int]`): `[x1, y1, x2, y2]` pixel coordinates.
  - `center_x`, `center_y` (`float`): Centroid coordinates.
  - `width`, `height`, `area` (`int`): Bounding box dimensions and surface area ($W \times H$).

#### 2. `ObjectAnalyzer` (`object_analyzer.py`)
- **Responsibility**: Enriches raw geometric detections with spatial positioning and domain-specific priority metadata without discarding any objects.
- **Inputs**: `List[DetectedObject]`, `img_width` (`int`).
- **Outputs**: `List[AnalyzedObject]`, adding:
  - `position` (`str`): `"LEFT"` (centroid $< \frac{1}{3} W$), `"CENTER"` ($\frac{1}{3} W \le \text{centroid} \le \frac{2}{3} W$), or `"RIGHT"` (centroid $> \frac{2}{3} W$).
  - `priority` (`int`): Numerical score ($0 - 10$) extracted from `PRIORITY_TABLE` (e.g., `person`: 9, `car`: 10, `chair`: 5, default: 1).

#### 3. `TargetSelector` (`target_selector.py`)
- **Responsibility**: Evaluates all enriched objects in the scene and isolates the single obstacle requiring immediate user action.
- **Inputs**: `List[AnalyzedObject]`.
- **Outputs**: `Optional[SelectedTarget]` (or `None` if scene is clear), containing:
  - All properties of `AnalyzedObject`.
  - `reason` (`str`): Explicit selection justification (e.g., `"Largest Bounding Box"`).

#### 4. `DecisionEngine` (`decision_engine.py`)
- **Responsibility**: Converts spatial target placement into tactile actuation signals and manages backend thread synchronization.
- **Inputs**: `Optional[SelectedTarget]`.
- **Outputs**: Motor command dictionary `{"left": int, "front": int, "right": int, "back": int}`, where active motor PWM is set to `255` and inactive motors are set to `0`.

---

# Hardware

The system utilizes modular, low-cost hardware components selected for high performance, portability, and minimal power consumption:

| Hardware Component | Role / Function | Selection Rationale |
| :--- | :--- | :--- |
| **Android Smartphone** | Primary Sensor & User Gateway | Equipped with high-resolution camera sensor, native CameraX hardware pipeline, Wi-Fi 5/6 connectivity, and battery power. Eliminates need for custom camera hardware. |
| **ESP32 Microcontroller** | Wireless Haptic Controller | Dual-core Tensilica LX6, built-in 802.11 b/g/n Wi-Fi, integrated 8-bit LEDC hardware PWM generator. Extremely cheap (~$4), reliable, and low latency. |
| **Motor Drivers (NPN Transistors / ULN2003 / MOSFET Board)** | Power Interface | ESP32 GPIO pins output max 40 mA at 3.3V (insufficient to drive motors directly). Driver circuit handles 5V / 3.7V switching up to 500 mA per motor channel. |
| **Vibration Motors (4x ERM / LRA Coin Motors)** | Tactile Actuators | Flat 1030/1027 coin-type vibration motors mounted on waist belt at 90° intervals (Left, Front, Right, Back) providing immediate spatial tactile cues. |
| **Power Supply (5V USB Power Bank / 3.7V Li-Po Battery)** | Mobile Power Source | Compact 5000 mAh power bank supplying regulated 5V power to the ESP32, motor drivers, and haptic belt assembly for 6+ hours of continuous mobility. |

---

# Software Stack

```
+-------------------------------------------------------------------------+
|                              FRONTEND & MOBILE                          |
|    Kotlin  |  Android CameraX  |  HTML5 / CSS3  |  JavaScript (ES6)      |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                              BACKEND & AI                               |
|    Python 3.10+  |  FastAPI  |  PyTorch  |  Ultralytics YOLO  |  OpenCV   |
|    NumPy         |  Uvicorn  |  WebSockets                          |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                             EMBEDDED FIRMWARE                           |
|    C++ / Arduino Framework  |  ESP-IDF LEDC PWM  |  ArduinoJson         |
+-------------------------------------------------------------------------+
```

### Programming Languages
- **Python**: Primary language for computer vision backend, AI inference, and socket streaming.
- **Kotlin**: Native language for Android Camera client application.
- **C++ / C**: Embedded firmware programming for ESP32 microcontroller.
- **JavaScript (ES6) / HTML5 / CSS3**: Web debugging dashboard and visual overlay interface.

### Libraries & Frameworks
- **Ultralytics YOLOv8**: Real-time object detection model.
- **PyTorch**: Deep learning backend framework with CUDA acceleration support.
- **OpenCV (`opencv-python`)**: Image decoding, zero-copy array operations, bounding box manipulation, and visual debugging.
- **FastAPI & Uvicorn**: High-performance asynchronous Web server framework.
- **AndroidX CameraX**: Modern Android camera framework guaranteeing hardware-level frame capture stability.
- **ArduinoJson**: Memory-efficient JSON parsing library for ESP32 microcontrollers.
- **PlatformIO / Arduino IDE**: Build and deployment pipeline for ESP32 firmware.

---

# Communication Architecture

HapticGuide uses a multi-protocol communication design tailored to the bandwidth and latency requirements of each link:

```
Android Phone ──────── Raw TCP Socket (Port 9000) ────────► Python Backend
                                                                  │
                                                        HTTP GET /command (Port 8000)
                                                                  │
                                                                  ▼
Vibration Motors ◄─────── PWM Signals (LEDC) ─────────── ESP32 Belt
```

### Channel Breakdown

#### 1. Android $\rightarrow$ Backend (Raw TCP Streaming)
- **Protocol**: Raw TCP Socket over Wi-Fi (Port 9000).
- **Packet Structure**:
  - `[0..3]` : 4-byte unsigned integer (big-endian) representing payload length $N$.
  - `[4..11]`: 8-byte double (big-endian) timestamp.
  - `[12..12+N]`: Raw JPEG compressed frame bytes.
- **Why Raw TCP Replaced HTTP for Camera Streaming**:
  - *HTTP Overhead*: Standard HTTP `POST` multipart/form-data uploads introduce heavy header parsing overhead (HTTP headers, boundary strings, MIME types) on every frame, consuming unnecessary CPU cycles and bandwidth.
  - *Socket Persistence*: Raw TCP maintains an open connection, removing HTTP handshake latency.
  - *No Nagle Delay*: Disabling Nagle's algorithm (`TCP_NODELAY`) sends frames immediately over the socket without waiting to pool small packets.
  - *Zero-Copy Buffering*: Reads network stream directly into reusable `memoryview` byte arrays without memory allocations per frame.

#### 2. Backend $\rightarrow$ ESP32 (HTTP Polling)
- **Protocol**: HTTP GET over Wi-Fi (Port 8000, `/command` endpoint).
- **Payload Format**: Lightweight JSON:
  ```json
  {
    "left": 0,
    "front": 255,
    "right": 0,
    "back": 0
  }
  ```
- **Optimization**: Uses HTTP Persistent Connections (`Connection: keep-alive`) and low socket timeout (150 ms) to poll at 25 Hz (every 40 ms).

#### 3. ESP32 $\rightarrow$ Motors (PWM Hardware Drive)
- **Protocol**: Analog Pulse-Width Modulation (LEDC PWM).
- **Frequency**: 5 kHz PWM frequency at 8-bit resolution ($0 - 255$ duty cycle).
- **Signal**: Direct hardware pin state changes driving motor transistor switches.

---

# Repository Structure

```
HapticGuide/
├── app/                        # Android Kotlin Project
│   └── hapticguide_app/        # Root of Android Studio project
│       ├── app/src/main/java/  # Kotlin source code (CameraManager, FrameUploader, MainActivity)
│       └── build.gradle.kts    # Android build configuration (AGP 9.0, SDK 36)
├── backend/                    # Python Computer Vision & Server Core
│   ├── ai_worker.py            # AI worker thread orchestrating inference pipeline
│   ├── camera_stream.py        # High-performance TCP frame receiver (Port 9000)
│   ├── decision_engine.py      # Spatial target to motor mapping logic
│   ├── detector.py             # YOLOv8 object detector wrapper (CUDA FP16)
│   ├── globals.py              # Shared memory thread locks & performance statistics
│   ├── main.py                 # FastAPI application server entry point
│   ├── object_analyzer.py      # Spatial partitioning (LEFT/CENTER/RIGHT) & priority mapping
│   ├── priority_table.py       # Object class risk score lookup definitions
│   ├── risk_estimator.py       # Distance & collision risk estimation module
│   ├── routes.py               # REST API route handlers (/receive, /command, /stats)
│   ├── shared_state.py         # Thread-safe frame slots & state containers
│   ├── target_selector.py      # Single target isolation algorithm (Rule V1: Max Area)
│   ├── tracker.py              # Multi-object tracking module
│   ├── yolov8n.pt              # YOLOv8 PyTorch model weights file
│   └── requirements.txt        # Python dependency manifest
├── esp32/                      # Microcontroller Firmware
│   ├── esp32_haptic_guide.ino  # Main Arduino/C++ firmware with fail-safe poller
│   ├── platformio.ini          # PlatformIO project build configuration
│   └── README.md               # Hardware pinout & wiring documentation
├── architecture.md             # Detailed internal architecture specification
├── benchmark.py                # Standalone performance benchmark script
├── requirements.txt            # Root Python dependencies
└── README.md                   # Complete Project Documentation (this file)
```

---

# Current Workflow

Step-by-step sequence of operations executed from application launch to tactile motor actuation:

```
1. User presses "Start Streaming" in Android App
                   │
2. CameraX captures YUV frame & scales to 416x416 JPEG
                   │
3. TCP socket transmits frame to Backend (Port 9000)
                   │
4. Backend TCP thread receives packet & stores in RawJpegSlot
                   │
5. AI Worker thread pulls frame & runs YOLOv8n GPU inference
                   │
6. ObjectAnalyzer categorizes detections into LEFT / CENTER / RIGHT
                   │
7. TargetSelector isolates closest obstacle (Largest Area)
                   │
8. DecisionEngine updates motor payload dict {"front": 255, ...}
                   │
9. ESP32 polls GET /command endpoint via HTTP (every 40 ms)
                   │
10. ESP32 parses JSON & writes 8-bit PWM to GPIO pins
                   │
11. Corresponding vibration motor vibrates on user's waist
```

1. **User Initiation**: The user opens the Android app and presses **Start Streaming**.
2. **Frame Capture**: Android `CameraManager` grabs a `YUV_420_888` frame from CameraX, converts it to NV21, downscales to 416x416, and compresses it into a high-quality JPEG bitmap.
3. **TCP Transmission**: `FrameUploader` writes a 4-byte size header followed by raw JPEG bytes directly to the persistent TCP socket connected to `backend_ip:9000`.
4. **Backend Reception**: `camera_stream.py` reads the binary stream into a pre-allocated bytearray buffer and places it into `_RawJpegSlot` (overwriting un-decoded frames if busy).
5. **Frame Decoding & AI Inference**: The dedicated `ai_worker` thread pulls the JPEG payload, decodes it into a BGR NumPy array using OpenCV, and executes FP16 GPU inference via `detector.py`.
6. **Spatial Analysis**: `object_analyzer.py` calculates object centroids and assigns spatial tags (`LEFT`, `CENTER`, `RIGHT`) based on column boundaries.
7. **Target Isolation**: `target_selector.py` evaluates all candidate objects and selects the single target with the largest bounding box area.
8. **Motor Command Formulation**: `decision_engine.py` converts spatial tag `CENTER` to `{"left": 0, "front": 255, "right": 0, "back": 0}` and writes it to `globals.latest_command` under a thread lock.
9. **Microcontroller Polling**: The ESP32 firmware executes its 40 ms loop timer, issuing an HTTP `GET /command` request to the backend server.
10. **PWM Signal Generation**: The ESP32 receives `HTTP 200 OK`, parses JSON using `ArduinoJson`, and sets LEDC Channel 1 (Front Motor GPIO 13) to duty cycle `255`.
11. **Tactile Perception**: The front vibration motor vibrates, warning the user of an obstacle directly ahead.

---

# Performance

Metrics measured on baseline test hardware (NVIDIA RTX 3060 GPU / Intel i7 CPU / Wi-Fi 5 Local Network / Android Snapdragon 8 Gen 1):

| Metric | Measured Value | Operational Notes |
| :--- | :--- | :--- |
| **Camera Capture FPS** | 30 FPS | Configurable in Android CameraX pipeline |
| **Network TCP Transport FPS** | 25 – 30 FPS | Zero-copy TCP stream over 5 GHz Wi-Fi |
| **YOLO Inference FPS** | 25 – 45 FPS | FP16 precision on CUDA GPU at 320/416 resolution |
| **End-to-End Latency** | 35 – 70 ms | Time elapsed from Android frame capture to ESP32 PWM drive |
| **Frame Resolution** | 416 x 416 px | Scaled for optimal speed/accuracy trade-off |
| **ESP32 Polling Frequency** | 25 Hz (40 ms) | Hardware timer loop polling rate |

> **Note**: Actual performance numbers vary depending on backend GPU hardware, network interference, CPU clock speed, and frame image complexity.

---

# Challenges Faced

### 1. HTTP Camera Streaming Bottleneck
- **Problem**: Uploading individual frames via standard HTTP `POST` multipart requests generated severe latency spikes (>200 ms) and connection drops due to repeated HTTP header allocation.
- **Solution**: Designed a custom binary raw TCP streaming protocol running on port 9000, disabling Nagle's algorithm (`TCP_NODELAY`) and implementing zero-copy buffer reception.

### 2. Camera Sensor Buffer Deadlocks
- **Problem**: Android CameraX buffer stalled whenever frame encoding or transmission took longer than 33 ms, freezing the camera preview.
- **Solution**: Separated image analysis from network transmission by closing the `ImageProxy` immediately after copying byte arrays and enforcing an `AtomicBoolean` single-slot frame guard.

### 3. RTSP Protocol Instability
- **Problem**: Attempting to stream video using RTSP (Real-Time Streaming Protocol) caused 2–3 seconds of latency buffering inside backend OpenCV `VideoCapture` pipelines.
- **Solution**: Abandoned RTSP media frameworks in favor of direct JPEG packet socket ingestion with drop-oldest frame mechanics.

### 4. GPU Context Switching & Event Loop Contention
- **Problem**: Running heavy PyTorch inference inside FastAPI `async` handlers blocked the Uvicorn asyncio event loop, causing HTTP timeouts for ESP32 requests.
- **Solution**: Isolated all deep learning execution onto a dedicated OS worker thread (`ai_worker.py`) using `threading.Thread` and atomic pointer swaps.

---

# Future Roadmap

```
Phase 1: Baseline Architecture (Completed)
[Raw TCP Streaming] ──► [YOLO Detection] ──► [Spatial Decision] ──► [ESP32 Haptic PWM]

Phase 2: Short-Term Enhancements (In Progress)
[Monocular Depth] ──► [Multi-Object ByteTrack] ──► [Proportional PWM Scaling]

Phase 3: Long-Term Autonomy (Planned)
[YOLOP Road Parsing] ──► [GPS/Voice Guidance] ──► [Pothole/Staircase Detection]
```

### Short-Term Objectives
- [ ] **Monocular Depth Map Integration**: Fusing Depth Anything V2 monocular depth maps to replace bounding box area proxies with metric distance values ($d_{meters}$).
- [ ] **ByteTrack Trajectory Tracking**: Tracking object movement vectors across consecutive frames to predict collision course trajectories.
- [ ] **Proportional Haptic PWM Scaling**: Modulating motor vibration intensity based on distance ($255$ for critical close range, $100$ for medium range, $0$ for clear path).

### Long-Term Objectives
- [ ] **YOLOP Multi-Task Panoptic Driving Perception**: Evaluating YOLOP for simultaneous object detection, drivable area segmentation, and lane line detection.
- [ ] **Pothole & Ground Elevation Hazard Detection**: Training custom vision models to identify ground depressions, curbs, and staircases.
- [ ] **Voice Navigation & GPS Integration**: Integrating turn-by-turn routing with audio prompts for outdoor navigation.

---

# How to Run

### 1. Prerequisites
- **Python**: Version 3.10 or higher.
- **Android Studio**: Ladybug or newer with Android SDK 36.
- **PlatformIO / Arduino IDE**: Installed with ESP32 board support.
- **Hardware**: Android Smartphone, ESP32 development board, 4x coin vibration motors with driver circuit, local Wi-Fi router.

---

### 2. Backend Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-username/HapticGuide.git
   cd HapticGuide
   ```

2. **Create and Activate Virtual Environment**:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```

4. **Launch the Server**:
   ```bash
   # Start the FastAPI server and TCP Stream Receiver
   python backend/main.py
   ```
   *The backend will display the server's local IP address and listening ports (HTTP: 8000, TCP: 9000).*

---

### 3. Android App Setup

1. Open Android Studio and choose **Open Project** $\rightarrow$ select `app/hapticguide_app`.
2. Connect your Android device via USB with **USB Debugging** enabled.
3. Ensure your phone is connected to the **same Wi-Fi network** as the backend computer.
4. Build and run the app on your device (`Shift + F10`).
5. Enter the Backend IP address (e.g., `192.168.1.100`) in the app settings field and tap **Start Streaming**.

---

### 4. ESP32 Firmware Setup

1. Open `esp32/esp32_haptic_guide.ino` in Arduino IDE or PlatformIO.
2. Update Wi-Fi credentials and backend server address:
   ```cpp
   const char* WIFI_SSID     = "YOUR_WIFI_SSID";
   const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
   const char* SERVER_CMD_URL = "http://192.168.1.100:8000/command";
   ```
3. Wire vibration motors to GPIO pins according to the pinout configuration:
   - **Left Motor**: GPIO 12
   - **Front Motor**: GPIO 13
   - **Right Motor**: GPIO 14
   - **Back Motor**: GPIO 27
4. Connect ESP32 via USB and upload firmware.
5. Open Serial Monitor at **115200 baud** to view real-time telemetry logs.

---

# Demo

Follow this procedure to demonstrate the full system to reviewers or judges:

1. **Start Backend**: Launch `python backend/main.py` on your laptop. Observe the terminal confirm server ready status on `0.0.0.0:8000` and TCP listener on `0.0.0.0:9000`.
2. **Power ESP32 Belt**: Turn on the ESP32 belt power supply. Verify via Serial Monitor or LED that the ESP32 connects to Wi-Fi and begins polling `/command` (displaying `applied PWM: 0, 0, 0, 0`).
3. **Launch Mobile App**: Open the HapticGuide app on the phone, input the laptop's Wi-Fi IP address, and tap **Start Streaming**.
4. **Observe Visual & Tactile Output**:
   - Point the camera at a person or chair located on your **Left**. Observe the left vibration motor activate.
   - Move the object directly to the **Center**. Observe the left motor stop and the front motor activate instantly.
   - Open the web dashboard in your browser (`http://localhost:8000`) to view live camera bounding boxes and telemetry graphs.

---

# Contributors

- **Lead Developer**: Utkarsh (*Placeholder*)
- **AI & Systems Architect**: (*Placeholder*)
- **Hardware & Embedded Engineer**: (*Placeholder*)

*Contributions, bug reports, and feature requests are welcome! Feel free to open an issue or pull request.*

---

# License

This project is licensed under the [MIT License](LICENSE) - see the `LICENSE` file for details.
