# HapticGuide: AI-Powered Wearable Haptic Navigation System

> **Comprehensive Technical Specification & Architecture Manual**  
> *HapticGuide is an open-source, ultra-low-latency assistive navigation platform for blind and visually impaired individuals. It combines smartphone computer vision, real-time instance segmentation, spatial collision risk modeling, GPS turn-by-turn routing with OpenStreetMap/OSRM, Groq Whisper voice guidance, and an ESP32 haptic belt delivering intuitive, multi-directional tactile cues without blocking auditory perception.*

---

## Table of Contents

1. [Executive Summary & Motivation](#1-executive-summary--motivation)
2. [Key Capabilities & Innovations](#2-key-capabilities--innovations)
3. [Complete System Architecture](#3-complete-system-architecture)
4. [Hardware Specification & Pinout](#4-hardware-specification--pinout)
5. [Communication Protocols & Transport Layer](#5-communication-protocols--transport-layer)
6. [Computer Vision & AI Avoidance Pipeline](#6-computer-vision--ai-avoidance-pipeline)
7. [Navigation, GPS, STT & Voice Subsystem](#7-navigation-gps-stt--voice-subsystem)
8. [Haptic Pulse Contract & Multi-Source Mixer](#8-haptic-pulse-contract--multi-source-mixer)
9. [ESP32 Firmware Architecture](#9-esp32-firmware-architecture)
10. [REST API & Telemetry Contract](#10-rest-api--telemetry-contract)
11. [Live Web Dashboard & Visualizer](#11-live-web-dashboard--visualizer)
12. [Benchmark Suite & Performance Metrics](#12-benchmark-suite--performance-metrics)
13. [Edge TFLite Export Pipeline](#13-edge-tflite-export-pipeline)
14. [Repository Structure](#14-repository-structure)
15. [Installation & Setup Guide](#15-installation--setup-guide)
16. [Demonstration & Verification Workflow](#16-demonstration--verification-workflow)
17. [License & Acknowledgments](#17-license--acknowledgments)

---

## 1. Executive Summary & Motivation

### The Problem
Globally, over 2.2 billion people live with vision impairments. Traditional navigation aids such as white canes only detect obstacles at ground level within immediate physical reach (~1 meter) and provide zero advance warning for head-height hazards, approaching pedestrians, or vehicles. Commercial digital solutions typically rely on audio synthesized speech or tones through headphones, which critically **blocks ambient environmental acoustics** (traffic, voices, echoes) that visually impaired individuals depend on for situational safety.

### The Solution: HapticGuide
**HapticGuide** provides a silent, hands-free "second sense." By streaming high-speed camera frames from a chest- or waist-mounted smartphone to an AI backend and coupling it with an ESP32-driven haptic belt:
1. **Silent Tactile Navigation**: Spatial hazards and turn-by-turn navigation instructions are translated into localized vibration pulses on the waist (Left, Right) and smartphone (Front/Straight), keeping the user's ears 100% open.
2. **Sub-50ms End-to-End Latency**: Custom zero-copy binary TCP frame streaming and FP16 accelerated inference ensure immediate real-time feedback at normal walking speeds.
3. **Dual-Layer Intelligence**: Seamlessly blends real-time **Obstacle Avoidance** (YOLOv8 instance segmentation, ByteTrack tracking, collision risk estimation) with **GPS Turn-by-Turn Wayfinding** (Groq Whisper voice recognition, OpenStreetMap POI search, OSRM routing).

### Comparison Matrix

| Feature / Aspect | White Cane | Smart Glasses (e.g., Envision / OrCam) | HapticGuide |
| :--- | :--- | :--- | :--- |
| **System Cost** | Low ($20–$50) | High ($2,000–$4,500) | Low (~$30 ESP32/belt + user's smartphone) |
| **Auditory Occlusion** | None | High (Bone conduction / speakers mask ambient cues) | **Zero (Silent waist/phone haptics)** |
| **Detection Scope** | Ground sweep only (<1m) | Text/Face reading; limited spatial awareness | **Full 3D spatial field + Dynamic tracking** |
| **Voice Wayfinding** | None | Cloud voice query | **Natural language Groq Whisper + OSM Routing** |
| **Hazard Prioritization**| None | Equal audio priority | **Deterministic Multi-Factor Collision Risk Matrix** |
| **Haptic Feedback** | Manual cane vibration | None | **Multi-Axis Non-Blocking PWM Pulse Sequencer** |

---

## 2. Key Capabilities & Innovations

### 1. Ultra-Low-Latency Raw TCP Camera Transport
- Replaced high-overhead HTTP/REST multipart uploads with a dedicated, persistent binary TCP protocol on port `9000`.
- Socket optimization with `TCP_NODELAY` (disabling Nagle's algorithm) and 512 KB receive socket buffers.
- Zero-copy buffer reuse with pre-allocated 256 KB memoryviews.
- Decoupled network and decoder loops via a thread-safe, single-slot `_RawJpegSlot` with latest-wins drop-oldest semantics, guaranteeing zero queue lag.

### 2. YOLOv8 Instance Segmentation & Poly-Contour Reasoning
- Powered by `yolov8n-seg.pt` (Ultralytics) running in FP16 precision on CUDA GPUs (with automatic CPU fallback).
- Extracts pixel-accurate boundary polygons, contour areas, bounding boxes, and object centroids.
- Visual debug renderer features 40% alpha-blended translucent polygon overlays, crisp boundary polylines, and class/priority/area/position tags.

### 3. Spatial Partitioning & Priority Matrix
- Frame horizontally partitioned into three 120° field-of-view zones: `LEFT` ($< 33\% W$), `CENTER` ($33\% - 66\% W$), and `RIGHT` ($> 66\% W$).
- Integrates domain-specific `PRIORITY_TABLE` ranking classes by physical hazard severity (e.g., `person`: 10, `bicycle`/`motorcycle`: 9, `car`/`bus`/`truck`: 8, `chair`: 7, `table`: 6, `trash can`/`bench`: 4).

### 4. Multi-Object ByteTrack Tracking
- Implements two-stage IoU association (matching high-confidence and low-confidence detections separately) to maintain track continuity through occlusions.
- Exponentially smoothed constant-velocity state estimation ($\mathbf{v}_x, \mathbf{v}_y$) for motion vector calculation.

### 5. Dynamic Collision Risk Estimation
- Assesses multi-factor collision hazard score ($0.0 \rightarrow 1.0$) for every active track based on:
  - **Area Ratio** ($\text{Area} / \text{Frame Area}$): Proximity proxy.
  - **Area Growth Rate** ($\Delta \text{Area} / \text{Area}_0$): Rate of approach / expanding bounding box.
  - **Centering Weight**: Critical walking trajectory bias for obstacles in the center column.
  - **Track Persistence**: Temporal confidence weighting over consecutive frames.

### 6. Voice-Activated GPS Navigation & Wayfinding
- **Groq Whisper STT (`whisper-large-v3-turbo`)**: High-accuracy voice transcription with wake-phrase gating (`"Hello Haptic Guide"` / `"Hey Haptic Guide"`).
- **Natural Language Parsing**: Automatic extraction of intent and target destinations (e.g., `"take me to the nearest coffee shop"`, `"navigate to Central Park"`).
- **OpenStreetMap Overpass POI Search**: Localized spatial search around user's current GPS fix.
- **OSRM Turn-by-Turn Walking Engine**: Generates complete walking routes, step geometries, road names, turn maneuvers, and bearing calculations.
- **Route Follower**: Real-time cross-track error computation, maneuver advance detection, and off-route reroute triggers.

### 7. Haptic Pulse Sequencer & Multi-Source Mixer
- **Obstacle Priority Guarantee**: Real-time obstacle warnings maintain absolute priority over any occupied belt motor.
- **Additive Navigation Pulses**: Clean turn maneuvers emitted without interfering with obstacle sensing (Left turn $\rightarrow 2$ pulses on left belt motor, Right turn $\rightarrow 2$ pulses on right belt motor, Front/Straight $\rightarrow 2$ pulses on smartphone vibrator).
- **Non-Blocking ESP32 Sequencer**: Hardware timer-driven PWM pulse bursts (80 ms ON / 80 ms OFF) executed smoothly without blocking serial or communication loops.

---

## 3. Complete System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            ANDROID CLIENT (Kotlin)                          │
│                                                                             │
│   ┌────────────────────────┐  Raw TCP (Port 9000)  ┌────────────────────┐   │
│   │ CameraX ImageAnalysis  │ ────────────────────► │ FrameUploader      │   │
│   │ YUV420 -> NV21 -> JPEG │   Length + JPEG Bytes │ (Atomic Guard)     │   │
│   └────────────────────────┘                       └────────────────────┘   │
│   ┌────────────────────────┐   HTTP POST /nav/gps   ┌────────────────────┐   │
│   │ FusedLocationProvider  │ ────────────────────► │ GPS / Fault Ingest │   │
│   └────────────────────────┘                       └────────────────────┘   │
│   ┌────────────────────────┐  HTTP POST /nav/voice ┌────────────────────┐   │
│   │ AudioRecord (Microphone)│ ────────────────────► │ Voice Audio Stream │   │
│   └────────────────────────┘                       └────────────────────┘   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PYTHON BACKEND SERVER (FastAPI)                    │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ camera_stream.py (TCP Server :9000)                                   │  │
│  │   _recv_loop (Zero-Copy) ──► _RawJpegSlot ──► _decoder_loop (cv2)     │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │ frame_slot.put()                     │
│                                      ▼                                      │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ ai_worker.py (Dedicated AI Execution Thread)                          │  │
│  │   1. detector.py        ── YOLOv8-Seg GPU FP16 (Masks + Bounding Boxes)│  │
│  │   2. object_analyzer.py ── Spatial Columns (L/C/R) + PRIORITY_TABLE   │  │
│  │   3. object_filter.py   ── Class Whitelist -> ObstacleObjects         │  │
│  │   4. tracker.py         ── ByteTrack 2-Stage IoU Association          │  │
│  │   5. risk_estimator.py  ── Collision Risk Score (0.0 - 1.0)           │  │
│  │   6. target_selector.py ── SelectedTarget (Largest Proximity Area)    │  │
│  │   7. decision_engine.py ── Raw Obstacle Command {L, F, R, B}          │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│  ┌───────────────────────────────────┴───────────────────────────────────┐  │
│  │ navigation/ Subsystem                                                 │  │
│  │   - stt.py      ── Groq Whisper STT + Wake Phrase + Intent Extraction │  │
│  │   - search.py   ── OpenStreetMap Overpass POI GeoSearch               │  │
│  │   - routing.py  ── OSRM Walking Engine (Steps, Turns, Bearings)       │  │
│  │   - follower.py ── Cross-track tracking, Maneuver Triggering          │  │
│  │   - emitter.py  ── Haptic Pulse Sequencer (START, L, R, FRONT)        │  │
│  │   - contract.py ── Multi-Source Mixer (Obstacle Wins on Belt Axes)    │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│  ┌───────────────────────────────────┴───────────────────────────────────┐  │
│  │ FastAPI REST & Web Visualizer Layer (routes.py)                       │  │
│  │   - GET /cmd    ── Mixed 4-Axis PWM {left, front, right, back}        │  │
│  │   - GET /stats  ── Performance & Telemetry JSON Snapshot             │  │
│  │   - GET /live   ── Glassmorphic Belt Visualizer (Jinja2 + SVG)        │  │
│  │   - /nav/*      ── Complete Navigation REST API                       │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
└──────────────────────────────────────┼──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ESP32 HAPTIC BELT CONTROLLER                       │
│                                                                             │
│   HTTP GET /cmd (Wi-Fi)  OR  UART Serial "M,l,f,r,b" / "LEFT" / "RIGHT"     │
│                                      │                                      │
│   ┌──────────────────────────────────▼───────────────────────────────────┐  │
│   │ main.cpp — Arduino-ESP32 Core 3.x LEDC Driver                        │  │
│   │   - Non-Blocking HapticSequencer State Machine                       │  │
│   │   - 5 kHz PWM Frequency, 8-Bit Duty Cycle Resolution                 │  │
│   │   - Active Pulsing: 80 ms ON / 80 ms OFF                             │  │
│   └──────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│            ┌─────────────────────────┴─────────────────────────┐            │
│            ▼                                                   ▼            │
│  ┌──────────────────────┐                             ┌──────────────────┐  │
│  │ Left Haptic Motor    │                             │ Right Haptic     │  │
│  │ (GPIO 27 / Driver 1) │                             │ (GPIO 26 / Drv 2)│  │
│  └──────────────────────┘                             └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Hardware Specification & Pinout

### Component Bill of Materials (BOM)

| Component | Part / Spec | Quantity | Description & Role |
| :--- | :--- | :--- | :--- |
| **Microcontroller** | ESP32-WROOM-32 DevKit V1 | 1 | Dual-core 240 MHz MCU, Wi-Fi 802.11 b/g/n, Bluetooth, hardware LEDC PWM. |
| **Vibration Actuators** | 1027 / 1030 Coin Vibration Motors | 2–4 | Flat ERM (Eccentric Rotating Mass) coin motors (3V–5V, ~80 mA). |
| **Motor Driver Board** | MOSFET / NPN Transistor Array | 1 | 2N2222 / ULN2003 / SI2302 N-Channel MOSFETs with flyback diodes & 1kΩ base resistors. |
| **Power Supply** | 5V USB Power Bank (5000 mAh) | 1 | Regulated 5V rail for ESP32 VIN and motor collector power. |
| **Belt Assembly** | Adjustable Elastic Tactical Belt | 1 | Secure waist mounting with insulated wiring harness. |
| **Smartphone** | Android Device (SDK 26+) | 1 | CameraX sensor node, GPS receiver, microphone, and user interface. |

### ESP32 Pin Mapping Table

| Function | ESP32 Pin | Peripheral / Channel | Electrical Characteristics |
| :--- | :--- | :--- | :--- |
| **Left Haptic Motor** | `GPIO 27` | LEDC PWM (5 kHz, 8-bit) | Active HIGH $\rightarrow$ Transistor Base/Gate (0–150 PWM) |
| **Right Haptic Motor**| `GPIO 26` | LEDC PWM (5 kHz, 8-bit) | Active HIGH $\rightarrow$ Transistor Base/Gate (0–150 PWM) |
| **Front Motor (Opt.)**| `GPIO 13` | LEDC PWM (5 kHz, 8-bit) | Reserved for obstacle front vibration |
| **Back Motor (Opt.)** | `GPIO 14` | LEDC PWM (5 kHz, 8-bit) | Reserved for obstacle rear vibration |
| **Status LED** | `GPIO 2` | Onboard Builtin LED | Active LOW/HIGH flash on serial command ingest |
| **Serial Telemetry** | `TX0 (GPIO 1)` / `RX0 (GPIO 3)` | Hardware UART0 | 115200 Baud, 8-N-1 |

---

## 5. Communication Protocols & Transport Layer

### 1. Raw TCP Binary Video Streaming (Port 9000)
The mobile app transmits an uninterrupted binary packet stream over a single persistent TCP socket:

```
┌────────────────────────┬───────────────────────────────────────────┐
│ Byte Offset            │ Field Description                         │
├────────────────────────┼───────────────────────────────────────────┤
│ [0 .. 3]               │ 4-byte unsigned integer (Big-Endian):     │
│                        │ Total Payload Length N (Bytes)            │
├────────────────────────┼───────────────────────────────────────────┤
│ [4 .. 4+N-1]           │ Compressed JPEG Frame Bytes               │
└────────────────────────┴───────────────────────────────────────────┘
```

#### Why Raw TCP Outperforms HTTP Multipart:
- **Zero Header Overhead**: No HTTP boundary markers, content-type strings, or status line allocations per frame.
- **Persistent Socket**: Eliminates TCP handshake and TLS/HTTP renegotiation jitter.
- **Nagle Disabled (`TCP_NODELAY = 1`)**: Dispatches frames immediately into the network stack without packet buffering.
- **Zero-Allocation Ingestion**: Python backend reads directly into a reusable `memoryview(bytearray(256 * 1024))`.

### 2. ESP32 Control Protocols
The backend supports dual communication modes for microcontroller command dispatch:

#### A. HTTP Polling (`GET /cmd`)
ESP32 polls `http://<server-ip>:8000/cmd` at 25 Hz with `Connection: keep-alive`:
```json
{
  "left": 0,
  "front": 255,
  "right": 0,
  "back": 0
}
```

#### B. Serial UART Command Protocol (115200 Baud)
For direct tethered USB or Bluetooth serial bridges:
- `M,<left>,<front>,<right>,<back>` — Sets direct 4-channel PWM values (e.g., `M,150,0,0,0`).
- `START` — Triggers 3-pulse start sequence on both motors.
- `LEFT` — Triggers 2-pulse maneuver on Left Motor (GPIO 27).
- `RIGHT` — Triggers 2-pulse maneuver on Right Motor (GPIO 26).
- `STOP` — Immediately zeroes all motor PWM channels.
- `PING` — Responds with `[ESP32] PONG` and flashes status LED.

---

## 6. Computer Vision & AI Avoidance Pipeline

The AI pipeline is structured as a decoupled, multi-stage processing graph executed on a dedicated background thread (`ai_worker.py`):

```
                       Input Frame (from frame_slot)
                                     │
                                     ▼
                   Stage 1: YOLODetector.detect()
                   - yolov8n-seg.pt (CUDA FP16, imgsz=320)
                   - Outputs List[DetectedObject] with Polygons & BBoxes
                                     │
                                     ▼
                 Stage 2: ObjectAnalyzer.analyze()
                 - Partition: LEFT (<33%), CENTER (33-66%), RIGHT (>66%)
                 - Enrich with PRIORITY_TABLE scores (0-10)
                                     │
                                     ▼
                   Stage 3: ObjectFilter.filter()
                   - Whitelist filter -> List[ObstacleObject]
                                     │
                                     ▼
                   Stage 4: ByteTracker.update()
                   - 2-Stage IoU Association + Constant Velocity Motion
                   - Stable IDs across frames -> List[TrackedObject]
                                     │
                                     ▼
                Stage 5: RiskEstimator.estimate_risk()
                - Calculates Multi-Factor Risk Score (0.0 - 1.0)
                - Explanatory reasons ("Large object", "Growing rapidly")
                                     │
                                     ▼
                Stage 6: TargetSelector.select()
                - Isolates closest high-risk target (Rule V1: Max Area)
                                     │
                                     ▼
               Stage 7: DecisionEngine.compute_motor_command()
               - Maps target position to discrete motor axis
               - Writes to globals.latest_command under mutex
```

### Mathematical Formulation of Collision Risk
The `RiskEstimator` calculates a composite risk index $R \in [0.0, 1.0]$ for each tracked obstacle:

$$R = \min\left(1.0, \, \left( w_{\text{area}} \cdot S_{\text{area}} + w_{\text{growth}} \cdot S_{\text{growth}} + w_{\text{pos}} \cdot S_{\text{pos}} + w_{\text{motion}} \cdot S_{\text{motion}} \right) \cdot F_{\text{persist}} \right)$$

Where:
- **Area Score**: $S_{\text{area}} = \min\left(1.0, \frac{\text{Area}_{\text{bbox}}}{0.20 \cdot W_{\text{frame}} \cdot H_{\text{frame}}}\right)$ ($w_{\text{area}} = 0.35$).
- **Growth Score**: $S_{\text{growth}} = 1.0$ if $\frac{\Delta \text{Area}}{\text{Area}_0} \ge 0.15$, else $0.5$ if $\ge 0.05$, else $0.0$ ($w_{\text{growth}} = 0.30$).
- **Position Score**: $S_{\text{pos}} = 1.0$ if $0.30 \le \frac{c_x}{W} \le 0.70$ (Center trajectory), else $0.4$ ($w_{\text{pos}} = 0.25$).
- **Motion Score**: $S_{\text{motion}} = \min\left(1.0, \frac{\sqrt{\Delta x^2 + \Delta y^2}}{50.0}\right)$ ($w_{\text{motion}} = 0.10$).
- **Persistence Factor**: $F_{\text{persist}} = \min\left(1.0, \frac{N_{\text{frames}}}{3}\right)$.

---

## 7. Navigation, GPS, STT & Voice Subsystem

The `backend/navigation` package provides a standalone turn-by-turn navigation engine:

```
                User Voice: "Hello Haptic Guide, take me to Pacific Mall"
                                       │
                                       ▼
                     Groq Whisper STT (whisper-large-v3-turbo)
                                       │
                         Transcript & Wake-Phrase Gating
                                       │
                         Extracted Query: "Pacific Mall"
                                       │
                                       ▼
                   OpenStreetMap Overpass API (search.py)
                   - Queries spatial POIs around current GPS fix
                   - Returns Ranked PlaceCandidate {lat, lon, dist}
                                       │
                                       ▼
                       OSRM Routing Engine (routing.py)
                       - Computes walking route profile
                       - Extracts steps, maneuvers, bearings, street names
                                       │
                                       ▼
                       Route Follower (follower.py)
                       - Tracks progress, cross-track error (<25m)
                       - Triggers imminent maneuvers (<20m)
                                       │
                                       ▼
                    Navigation Haptic Emitter (emitter.py)
                    - Emits deduplicated haptic pulse waveforms
```

### Complete Navigation Endpoint Manifest

| Method | Endpoint | Description | Key Request / Response Parameters |
| :--- | :--- | :--- | :--- |
| `POST` | `/nav/gps` | Ingests phone GPS location fix | In: `{latitude, longitude, accuracy_m}`<br>Out: `{ok: true, health, status}` |
| `POST` | `/nav/gps/fault` | Ingests location hardware faults | In: `{health: "PERMISSION_DENIED" \| "NO_FIX", detail}` |
| `POST` | `/nav/voice` | Ingests voice audio for STT & routing | In: Multipart form file or `{audio_base64}`<br>Out: `{transcript, destination, route}` |
| `POST` | `/nav/search` | OpenStreetMap POI search | In: `{query: "hospital", radius_m: 5000}`<br>Out: `{destination: {name, lat, lon}}` |
| `POST` | `/nav/route` | Calculates OSRM walking route | In: `{origin_latitude, origin_longitude, ...}`<br>Out: `{route: {total_distance_m, steps}}` |
| `POST` | `/nav/start` | Commences live route following | In: None $\rightarrow$ Out: `{progress: {current_instruction, ...}}` |
| `GET`  | `/nav/progress`| Polls real-time route progress | Out: `{distance_to_next_m, next_maneuver, is_arrived}` |
| `GET`  | `/nav/status`  | Current navigation session state | Out: `{status: "NAVIGATING", current_location, destination}` |
| `POST` | `/nav/reset`   | Resets navigation state to IDLE | Out: `{ok: true, message: "Navigation reset to IDLE."}` |

---

## 8. Haptic Pulse Contract & Multi-Source Mixer

### Haptic Event Specification

| Event Type | Target Actuators | Pulse Count | Pulse ON Duration | Pulse OFF Duration | Physical Meaning |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `NAVIGATION_START` | Belt Left, Belt Right, Phone Front | 3 | 80 ms | 80 ms | Navigation session initiated |
| `NAVIGATION_LEFT`  | Belt Left (GPIO 27) | 2 | 80 ms | 80 ms | Upcoming turn left |
| `NAVIGATION_RIGHT` | Belt Right (GPIO 26) | 2 | 80 ms | 80 ms | Upcoming turn right |
| `NAVIGATION_FRONT` | Smartphone Vibrator | 2 | 80 ms | 80 ms | Continue straight ahead |
| `NAVIGATION_ARRIVAL`| None (All OFF) | 0 | 0 ms | 0 ms | Reached destination |

### Multi-Source Mixing Logic (`contract.py` & `emitter.py`)

The mixer guarantees user safety by prioritizing physical obstacle avoidance over routing guidance:

```python
# Mixer Priority Contract Rules:
# 1. Obstacle detection has ABSOLUTE priority on every belt axis it occupies.
# 2. Navigation never writes to ESP32 front (GPIO 13) or back (GPIO 14).
# 3. If obstacle PWM > 0 on left/right: Obstacle PWM is preserved.
# 4. If obstacle PWM == 0 on left/right: Navigation pulse PWM is passed through.
# 5. Phone vibrator is a navigation-only channel for straight maneuvers.
```

---

## 9. ESP32 Firmware Architecture

The ESP32 firmware (`esp32/src/main.cpp`) is built on **Arduino-ESP32 Core 3.x** using the modern `ledcAttach` / `ledcWrite` driver architecture.

### Key Implementation Details
- **LEDC Hardware PWM**: Frequency configured to **5,000 Hz** at **8-bit resolution** ($0 - 255$ duty cycle, scaled to max duty $150$ for optimal tactile perception).
- **Non-Blocking Sequencer (`HapticSequencer`)**: Executes multi-pulse timing schedules (`millis()` state machine) without using `delay()`, ensuring real-time serial responsiveness.
- **Fail-Safe Watchdog**: Automatically disables all motor channels if no valid serial/HTTP heartbeat is received within timeout windows.

```cpp
// PlatformIO / ESP32 Core 3.x Initialization Example
ledcAttach(PIN_MOTOR_LEFT,  5000, 8);  // GPIO 27 -> 5 kHz, 8-bit
ledcAttach(PIN_MOTOR_RIGHT, 5000, 8);  // GPIO 26 -> 5 kHz, 8-bit
```

---

## 10. REST API & Telemetry Contract

### Core Backend Endpoints

#### 1. `GET /cmd`
Returns the mixed 4-axis motor command for the ESP32 belt.
```json
{
  "left": 0,
  "front": 255,
  "right": 0,
  "back": 0
}
```

#### 2. `GET /stats`
Returns an instantaneous operational and performance snapshot:
```json
{
  "camera_fps": 30.0,
  "yolo_fps": 38.5,
  "ai_fps": 38.5,
  "recv_fps": 30.0,
  "yolo_time_ms": 14.2,
  "frame_age_ms": 26.4,
  "current_target": "CENTER",
  "current_command": {"left": 0, "front": 255, "right": 0, "back": 0},
  "current_resolution": "640×480",
  "client_ip": "192.168.1.105",
  "connected": true
}
```

#### 3. `GET /health`
Liveness probe for monitoring tools and status dashboards.

---

## 11. Live Web Dashboard & Visualizer

Navigating to `http://localhost:8000/live` in any web browser opens the real-time visualizer:

- **SVG Smartphone Assembly**: Realistic glass-back reflections and forward volumetric flashlight bloom effect.
- **Technical Woven Belt Representation**: Displays active waist-belt placement with dynamic haptic motor pulses.
- **Live Animated Indicators**: Left and Right motor nodes illuminate and pulse in real time corresponding to active PWM outputs.
- **Real-Time Telemetry Gauges**: Continuously updates Camera FPS, YOLO Inference Latency, Frame Age, and Active Obstacle Targets via lightweight background polling.

---

## 12. Benchmark Suite & Performance Metrics

The project includes an automated end-to-end benchmarking harness (`backend/benchmark.py` and `benchmark.py`) that tests synthetic frame streaming across 4 resolution profiles:

### Benchmark Results (NVIDIA RTX 3060 / Intel i7-12700H / 5 GHz Wi-Fi)

| Resolution | Recv FPS | Decode FPS | Decode Time | YOLO FP16 ms | Pipeline Latency | Bandwidth | Recommended Use |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **320 × 240** | 30.0 FPS | 30.0 FPS | 0.8 ms | 8.4 ms | **18.2 ms** | 0.45 MB/s | Ultra-low bandwidth / Edge CPU |
| **480 × 360** | 30.0 FPS | 30.0 FPS | 1.2 ms | 11.2 ms | **22.6 ms** | 0.82 MB/s | Balanced mobile performance |
| **640 × 480** | 30.0 FPS | 30.0 FPS | 1.8 ms | 14.5 ms | **26.4 ms** | 1.35 MB/s | **Default / Optimal Trade-off** |
| **848 × 480** | 28.5 FPS | 28.5 FPS | 2.4 ms | 19.8 ms | **35.1 ms** | 1.90 MB/s | Wide-angle outdoor environments |

---

## 13. Edge TFLite Export Pipeline

For environments requiring on-device mobile execution directly on Android without an external Python server, `export_tflite.py` provides a cross-platform conversion script:

```
                    PyTorch Model (backend/yolov8n.pt)
                                   │
                                   ▼  Step 1: Ultralytics ONNX Export (opset 12)
                     ONNX Model (yolov8n_export.onnx)
                                   │
                                   ▼  Step 2: onnx2tf Conversion (Windows compatible)
                     TFLite Model (yolo_obstacle.tflite)
                                   │
                                   ▼  Step 3: Asset Packaging
          app/hapticguide_app/app/src/main/assets/yolo_obstacle.tflite
```

### Running the Export:
```bash
# Activate virtual environment
.venv\Scripts\activate

# Run two-step ONNX -> TFLite converter
python export_tflite.py
```

---

## 14. Repository Structure

```
HapticGuide/
├── app/                                # Mobile Application
│   └── hapticguide_app/                # Android Studio Project (Kotlin, CameraX, Compose)
│       ├── app/src/main/
│       │   ├── java/com/hapticguide/   # MainActivity, CameraManager, FrameUploader
│       │   └── assets/                 # On-device TFLite models & label maps
│       └── build.gradle.kts            # Android build configuration (SDK 36, AGP 9.0)
│
├── backend/                            # Python AI Server & Navigation Core
│   ├── navigation/                     # Navigation Subsystem
│   │   ├── contract.py                 # Haptic pulse timing specifications & mixer contract
│   │   ├── emitter.py                  # Real-time haptic pulse sequencer & deduplicator
│   │   ├── follower.py                 # Turn-by-turn route progress & off-route detector
│   │   ├── gps.py                      # GPS fix parser, haversine distance & fault handler
│   │   ├── routes.py                   # Navigation REST API router (/nav/*)
│   │   ├── routing.py                  # OSRM walking route engine & bearing calculator
│   │   ├── search.py                   # OpenStreetMap Overpass POI destination search
│   │   ├── state.py                    # NavigationState machine & data containers
│   │   └── stt.py                      # Groq Whisper STT & wake-phrase extractor
│   │
│   ├── templates/                      # Jinja2 HTML Templates
│   │   └── live_dashboard.html         # Real-time glassmorphic haptic belt visualizer
│   │
│   ├── ai_worker.py                    # Dedicated background AI execution thread
│   ├── benchmark.py                    # In-backend resolution benchmark harness
│   ├── camera_stream.py                # High-performance raw TCP socket receiver (Port 9000)
│   ├── decision_engine.py              # Spatial position to motor channel mapper
│   ├── detector.py                     # YOLOv8-Seg GPU/FP16 segmentation wrapper
│   ├── globals.py                      # Shared memory state, mutex locks & perf counters
│   ├── main.py                         # FastAPI server entry point & lifespan manager
│   ├── object_analyzer.py              # Spatial column partitioning (L/C/R) & priority scoring
│   ├── object_filter.py                # Navigation obstacle whitelist filter
│   ├── priority_table.py               # Domain risk table for object classes
│   ├── risk_estimator.py               # Multi-factor collision risk estimation engine
│   ├── routes.py                       # Core FastAPI routes (/cmd, /stats, /health, /live)
│   ├── shared_state.py                 # Thread-safe FrameSlot & StreamStats singletons
│   ├── target_selector.py              # Proximity target selector (Rule V1: Max Area)
│   ├── tracker.py                      # Multi-object ByteTrack tracking module
│   ├── requirements.txt                # Python backend dependencies
│   ├── yolov8n-seg.pt                  # YOLOv8 nano segmentation PyTorch weights
│   └── yolov8n.pt                      # YOLOv8 nano detection PyTorch weights
│
├── esp32/                              # Embedded Microcontroller Firmware
│   ├── src/
│   │   └── main.cpp                    # ESP32 C++ firmware (Arduino-ESP32 Core 3.x LEDC driver)
│   ├── platformio.ini                  # PlatformIO build configuration
│   └── README.md                       # Hardware wiring & pinout diagrams
│
├── ref_img/                            # UI Design & SVG Vector Assets
│   ├── Phone.svg                       # Detailed SVG smartphone graphic
│   ├── belt.svg                        # Detailed SVG haptic belt graphic
│   └── haptic-motor.svg                # Detailed SVG coin vibration motor graphic
│
├── .env                                # Environment variables (GROQ_API_KEY, PORT)
├── architecture.md                     # Detailed internal architecture specification
├── benchmark.py                        # Root benchmark suite runner
├── export_tflite.py                    # PyTorch -> ONNX -> TFLite conversion pipeline
├── requirements.txt                    # Top-level dependencies manifest
└── README.md                           # Master Documentation (this file)
```

---

## 15. Installation & Setup Guide

### 1. Prerequisites
- **Python**: Version 3.10 or higher.
- **CUDA Toolkit** *(Optional, recommended)*: CUDA 11.8 / 12.x with cuDNN for GPU acceleration.
- **Android Studio**: Ladybug / Hedgehog or newer with Android SDK 36.
- **PlatformIO / VS Code** or **Arduino IDE**: With ESP32 board support installed.
- **Groq API Key**: Obtain a free API key from [console.groq.com](https://console.groq.com) for voice STT.

---

### 2. Environment Configuration
Create a `.env` file in the project root:
```env
GROQ_API_KEY=gsk_your_groq_api_key_here
PORT=8000
```

---

### 3. Backend Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/kreeti22/HapticGuide.git
   cd HapticGuide
   ```

2. **Create and Activate Virtual Environment**:
   ```bash
   python -m venv .venv

   # Windows (PowerShell):
   .venv\Scripts\Activate.ps1

   # Linux / macOS:
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```

4. **Launch the AI Server**:
   ```bash
   python backend/main.py
   ```
   *Follow the interactive prompt (default TCP Port: `9000`, Debug window: `Y`). The terminal will display active HTTP and TCP listening addresses.*

---

### 4. ESP32 Firmware Flashing

1. Connect the ESP32 to your computer via USB.
2. Open the `esp32` directory in **PlatformIO** (VS Code) or open `esp32/src/main.cpp` in **Arduino IDE**.
3. Verify the pin assignments match your hardware setup (`PIN_MOTOR_LEFT = 27`, `PIN_MOTOR_RIGHT = 26`).
4. Build and upload the firmware:
   ```bash
   # PlatformIO CLI:
   pio run --target upload
   ```
5. Open the Serial Monitor at **115200 baud** to confirm initialization:
   ```
   ==================================================
          HapticGuide ESP32 Motor Controller         
          Arduino-ESP32 Core 3.x LEDC Driver         
   ==================================================
   [ESP32] Motor 1 (Left)  -> GPIO 27 [OK]
   [ESP32] Motor 2 (Right) -> GPIO 26 [OK]
   [ESP32] Ready. Listening for serial commands...
   ```

---

### 5. Android Client Setup

1. Open `app/hapticguide_app` in **Android Studio**.
2. Connect your Android phone via USB with **USB Debugging** enabled.
3. Build and install the application (`Run 'app'`).
4. In the app settings screen:
   - Enter your computer's local Wi-Fi IP address (e.g., `192.168.1.100`).
   - Set the TCP port to `9000`.
5. Tap **Start Streaming**.

---

## 16. Demonstration & Verification Workflow

### Step-by-Step System Verification

1. **Start Backend**: Launch `python backend/main.py`. Ensure terminal logs confirm YOLOv8 model loading on CUDA/CPU.
2. **Start Video Stream**: In the Android app, tap **Start Streaming**.
   - Observe the terminal display incoming TCP frame statistics (`Recv FPS: 30.0`, `Decode Time: ~1.8 ms`).
   - The OpenCV debug window `"HapticGuide AI Debug"` will appear displaying real-time segmentation masks.
3. **Verify Obstacle Avoidance**:
   - Walk toward an obstacle on your **Left**: Notice the left motor activate (or serial output `[ESP32] OK: LEFT MOTOR`).
   - Position an obstacle in the **Center**: Notice the front motor signal fire (`"front": 255`).
   - Position an obstacle on your **Right**: Notice the right motor activate.
4. **Verify Voice Navigation**:
   - Send a voice command to `/nav/voice` or tap the voice button in the mobile app:
     *"Hello Haptic Guide, take me to the nearest pharmacy."*
   - Observe the backend transcribe via Groq Whisper, query OpenStreetMap Overpass, compute an OSRM route, and begin live route following with distinct 2-pulse turn indications.
5. **Open Web Visualizer**:
   - Open `http://localhost:8000/live` to watch the live SVG haptic belt dashboard and performance gauges.

---

## 17. License & Acknowledgments

### License
This project is licensed under the **MIT License** — see the `LICENSE` file for details.

### Acknowledgments
- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) for real-time segmentation models.
- [OpenStreetMap](https://www.openstreetmap.org/) & [Overpass API](https://overpass-api.de/) for open geospatial data.
- [Project OSRM](http://project-osrm.org/) for routing network infrastructure.
- [Groq](https://groq.com/) for ultra-fast Whisper speech-to-text inference.
