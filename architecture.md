# HapticGuide — System Architecture

> Last updated: August 2026
> Stack: Android (Kotlin / CameraX / Compose) + Python (FastAPI / PyTorch / Ultralytics)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Data Flow](#2-high-level-data-flow)
3. [Android Application](#3-android-application)
4. [Backend Transport Layer](#4-backend-transport-layer)
5. [AI Pipeline](#5-ai-pipeline)
6. [Shared State and Locking](#6-shared-state-and-locking)
7. [Threading Model](#7-threading-model)
8. [API Contract](#8-api-contract)
9. [Performance Design](#9-performance-design)
10. [Build Configuration](#10-build-configuration)
11. [Module Dependency Map](#11-module-dependency-map)
12. [Key Design Decisions](#12-key-design-decisions)

---

## 1. System Overview

HapticGuide is a real-time obstacle avoidance system for visually impaired users.
The phone camera continuously streams frames to a Python server running on a laptop
or edge device. The server runs depth estimation and object detection, then sends
vibration motor commands to an ESP32 haptic driver worn by the user.

```
┌─────────────────────┐        Wi-Fi / USB        ┌──────────────────────────┐
│   Android Phone     │ ──── POST /receive ──────► │   Python Backend         │
│   (camera + UI)     │                            │   (FastAPI + AI models)  │
│                     │ ◄─── GET /command ──────── │                          │
└─────────────────────┘                            └──────────┬───────────────┘
                                                              │ Serial / BLE
                                                   ┌──────────▼───────────────┐
                                                   │   ESP32 Haptic Driver    │
                                                   │   (vibration motors)     │
                                                   └──────────────────────────┘
```

**Three physical nodes:**
- **Android phone** — captures frames, streams them, drives the UI.
- **Python server** — runs all AI inference, produces motor commands.
- **ESP32** — polls the server for the latest command, drives the motors.


---

## 2. High-Level Data Flow

```
Android Camera Sensor
        │  YUV_420_888 frames @ up to 15 FPS
        ▼
CameraManager.processImageFrame()
        │  YUV → NV21 → JPEG (416×416, quality 70)
        ▼
FrameUploader.uploadFrame()
        │  multipart/form-data  POST /receive
        ▼
────────────────────────────── NETWORK ──────────────────────────────
        ▼
routes.py  POST /receive
        │  JPEG decode → BGR ndarray
        │  pointer-swap into globals.latest_frame
        │  signal globals.frame_event
        │  return {"status": "ok"}   ← HTTP response ends here
        ▼
────────────────── BACKGROUND THREAD (ai-worker) ────────────────────
        ▼
worker._ai_worker()
        │  grab latest_frame atomically
        ▼
ai_pipeline.process_frame()
        │
        ├─ Stage 1: depth_pipeline.estimate_depth()
        │           Depth Anything V2-Small → float32 depth map (H×W)
        │
        ├─ Stage 2: depth_obstacle_detector.detect_obstacles()
        │           Split lower 65% into LEFT / CENTER / RIGHT
        │           Median depth per region vs threshold (4.0)
        │           → ObstacleReport {flags, depths, any_obstacle}
        │
        ├─ [Early exit if no obstacle] → motor={0,0,0,0}
        │
        ├─ Stage 3: crop_generator.generate_crops()
        │           Connected-component analysis on near-depth mask
        │           Tight bounding rect per flagged region
        │           Crop from original RGB frame
        │           → List[ObstacleCrop]  (sorted closest-first)
        │
        ├─ Stage 4: yolo_classifier.classify_crops()
        │           YOLOv8n on each crop (never full frame)
        │           → List[ClassifiedCrop]  (label + confidence)
        │
        └─ Stage 5: decision_engine.make_decision()
                    Region → motor axis mapping
                    Fire motor for closest obstacle only
                    → DecisionResult {motor, obstacles}
        │
        ▼
globals.latest_command updated atomically
        │
        ▼
────────────────────────── ESP32 polling ────────────────────────────
        ▼
GET /command  → {"left": 0, "front": 255, "right": 0, "back": 0}
        │
        ▼
ESP32 PWM motor driver → haptic vibration worn by user
```


---

## 3. Android Application

### 3.1 Module Structure

```
com.hapticguide.camera/
├── MainActivity.kt        UI entry point, permission handling, Compose host
├── CameraManager.kt       CameraX setup, frame extraction, JPEG encoding
├── FrameUploader.kt       OkHttp HTTP client, one-at-a-time upload guard
└── SettingsManager.kt     SharedPreferences wrapper for server address
```

### 3.2 MainActivity

`MainActivity` is a `ComponentActivity`. On `onCreate` it:

1. Requests `CAMERA` permission via `ActivityResultContracts.RequestPermission`.
2. Instantiates `SettingsManager`, `FrameUploader`, and `CameraManager`.
3. Calls `setContent` to render the Compose UI tree.
4. Sets `FLAG_KEEP_SCREEN_ON` so the screen never dims during a session.

The `CameraStreamerScreen` composable renders:
- A full-screen `AndroidView` wrapping a CameraX `PreviewView` (the live camera feed).
- A translucent bottom card overlaid on top showing streaming FPS, connection status, and a server address text field.
- A pulsing status dot that turns green when streaming, red on error, yellow otherwise.

State (`connectionStatus`, `totalFramesSent`, `currentFps`) is held as `mutableStateOf` properties on the Activity and passed down as parameters so Compose re-renders reactively without a ViewModel.

### 3.3 CameraManager

Owns two CameraX use cases bound to the activity lifecycle:

| Use case | Purpose |
|---|---|
| `Preview` | Renders the live feed into the `PreviewView` in the UI |
| `ImageAnalysis` | Delivers raw `YUV_420_888` frames to `processImageFrame()` |

**Resolution selection** uses the modern `ResolutionSelector` + `ResolutionStrategy` API (not the deprecated `setTargetResolution`). Target is 640×480; the fallback rule is `CLOSEST_LOWER_THEN_HIGHER`.

**Backpressure strategy** is `STRATEGY_KEEP_ONLY_LATEST` — CameraX drops frames automatically when the analyzer is busy. This means the pipeline never builds up a queue.

**Frame processing pipeline (per frame):**

```
ImageProxy (YUV_420_888)
    │  yuv420ToNv21() — writes directly into a preallocated ByteArray
    ▼
NV21 ByteArray
    │  YuvImage.compressToJpeg() — quality 85, into reusable ByteArrayOutputStream
    ▼
Decoded Bitmap (original resolution)
    │  Bitmap.createScaledBitmap(416, 416, filter=false) — nearest-neighbour
    ▼
Scaled Bitmap 416×416
    │  compress(JPEG, quality 70) → jpegBytes
    │  originalBitmap.recycle() + scaledBitmap.recycle()
    ▼
imageProxy.close()   ← IMMEDIATELY after encoding, before network call
    │
    ▼
FrameUploader.uploadFrame(serverAddress, jpegBytes, callback)
```

Closing `ImageProxy` before the upload starts is critical — it releases the camera sensor buffer back to CameraX immediately, preventing sensor stalls.

**Throttling:** A `minIntervalMs = 66L` guard enforces a maximum of 15 FPS upload rate.

**Drop condition:** If `frameUploader.isUploading` is already `true`, the current frame is closed and discarded without encoding.

### 3.4 FrameUploader

Uses a single `OkHttpClient` with 2-second timeouts on connect, write, and read.

The `isUploading: AtomicBoolean` flag acts as a one-slot semaphore. `compareAndSet(false, true)` is called at the top of `uploadFrame`. If it returns `false`, the frame is dropped immediately — no queue is ever built.

The network call is launched on `Dispatchers.IO` inside the `CoroutineScope` passed in from `MainActivity.lifecycleScope`.

URL construction handles both bare IP:port strings and full `http://` URLs so the user can type either format into the settings field.

### 3.5 SettingsManager

Thin wrapper around `SharedPreferences`. Stores and retrieves a single key: the server address string (default `192.168.1.100:8000/receive`). Changes are committed with `apply()` (asynchronous, non-blocking).


---

## 4. Backend Transport Layer

### 4.1 Module Structure

```
backend/
├── main.py          FastAPI app factory, lifespan hooks, uvicorn entry point
├── routes.py        HTTP endpoint handlers (POST /receive, GET /command, GET /stats)
├── globals.py       All shared mutable state + locks + perf counters
├── worker.py        Background AI worker thread + stats printer thread
└── ai_pipeline.py   AI pipeline orchestrator (calls stages 1–5)
```

### 4.2 main.py

Creates the `FastAPI` app and registers the router from `routes.py`.

Uses the modern `@asynccontextmanager` lifespan pattern (not the deprecated `@app.on_event`):
- **Startup:** calls `worker.start_workers()` — spawns the AI worker and stats printer threads.
- **Shutdown:** calls `worker.stop_workers()` — sets `stop_event` to signal both threads.

`workers=1` is enforced in the uvicorn call. Multiple workers would create competing AI threads fighting over the same GPU, causing VRAM exhaustion.

A port finder scans ports 8000–8019 and binds to the first free one, so dev restarts never fail on a busy port.

Heavy imports (`torch`, `transformers`, `ultralytics`) are never imported at the module level of `main.py`. They load lazily when `worker.py` imports `ai_pipeline.py` — only on the worker thread, not on the event loop.

### 4.3 routes.py

Three endpoints. Zero inference in any of them.

#### POST /receive

**Purpose:** Accept a JPEG frame from Android, decode it, store it.

**Latency budget:**
```
Read multipart body     ~1–5 ms  (network I/O, unavoidable)
cv2.imdecode()          ~1–3 ms  (JPEG decode)
threading.Lock acquire  < 1 µs   (pointer swap only)
JSONResponse write      < 1 ms
──────────────────────────────
Total server-side:      ~3–9 ms
```

**Steps:**
1. Validate `content_type` is `image/jpeg` or `image/jpg` → 415 if not.
2. Read body bytes → 400 if empty.
3. `cv2.imdecode()` → 422 if decode fails.
4. Acquire `frame_lock`, overwrite `globals.latest_frame` (old frame discarded), release lock.
5. Call `globals.frame_event.set()` to wake the AI worker.
6. Call `globals.record_receive()` to increment the perf counter.
7. Return `{"status": "ok"}`.

#### GET /command

**Purpose:** Return the latest motor command to the ESP32.

Acquires `command_lock`, makes a shallow `dict()` copy of `globals.latest_command`, releases lock. Returns immediately. If the AI worker has not yet run, returns the safe all-zero default.

#### GET /stats

**Purpose:** Developer / monitoring endpoint.

Calls `globals.get_stats()` which reads the last published 1-second snapshot under `perf_lock`. Returns:
```json
{
    "receive_fps": 28.0,
    "ai_fps": 12.3,
    "avg_inference_ms": 81.2
}
```


---

## 5. AI Pipeline

The pipeline is depth-first. Depth runs on every frame. YOLO only runs when depth has already confirmed a nearby obstacle exists.

### 5.1 Stage 1 — Depth Anything V2 (`depth_pipeline.py`)

**Model:** `depth-anything/Depth-Anything-V2-Small-hf` loaded from HuggingFace.

**Device:** CUDA if available, CPU otherwise. fp16 on CUDA for ~2× throughput.

**Inference resolution:** Frame is down-sampled to 384×384 before inference. The result is bilinearly upsampled back to original frame dimensions using `torch.nn.functional.interpolate`.

**Output:** `float32` ndarray of shape `(H, W)`. Higher values = physically closer to the camera. Values are relative (not metric metres).

**Memory management:** `torch.no_grad()` prevents gradient graph allocation. Inference runs in fp16 on GPU; the upsample step is always done in fp32 to avoid bilinear artefacts from half-precision.

### 5.2 Stage 2 — Depth Obstacle Detector (`depth_obstacle_detector.py`)

Operates entirely on the depth map — no image data.

**Sky ignore:** The top 35% of rows are discarded. This eliminates sky, ceiling, and distant background that is never on the user's walking path.

**Region split:** The remaining lower 65% is split into three equal vertical columns:

```
│◄── 1/3 ──►│◄── 1/3 ──►│◄── 1/3 ──►│
│   LEFT    │   CENTER   │   RIGHT   │
│           │            │           │
```

**Detection logic:** `np.median()` is computed for each region's depth patch. If the median exceeds `OBSTACLE_DEPTH_THRESHOLD` (default `4.0`), that region is flagged.

**Output:** `ObstacleReport` TypedDict:
```python
{
    "flags":        {"left": bool, "center": bool, "right": bool},
    "depths":       {"left": float, "center": float, "right": float},
    "any_obstacle": bool
}
```

If `any_obstacle` is `False`, the pipeline returns `{"left":0,"front":0,"right":0,"back":0}` immediately and YOLO never runs.

### 5.3 Stage 3 — Crop Generator (`crop_generator.py`)

Only runs when at least one region is flagged.

For each flagged region:

1. Extract the depth patch for that column (lower 65% only).
2. Build a binary mask: pixels where `depth > threshold`.
3. Run `cv2.connectedComponentsWithStats` on the mask to find the largest contiguous near-depth blob.
4. Discard blobs smaller than `MIN_BLOB_AREA = 200` pixels (noise filtering).
5. Extract the tight bounding rect of the largest blob.
6. Translate coordinates to full-frame pixel space.
7. Add `CROP_PADDING = 8` pixels on all sides (gives YOLO boundary context).
8. Clamp to frame boundaries.
9. Slice the crop from the original BGR frame (NumPy view, no copy).

**Output:** `List[ObstacleCrop]` sorted by `median_depth` descending (closest first):
```python
{
    "region":       "left" | "center" | "right",
    "bbox":         [x1, y1, x2, y2],   # full-frame coordinates
    "crop":         np.ndarray,          # BGR view into original frame
    "median_depth": float
}
```

### 5.4 Stage 4 — YOLO Classifier (`yolo_classifier.py`)

Only runs when crops exist.

**Model:** YOLOv8n (`yolov8n.pt`), loaded once at import time. fp16 on CUDA, fp32 on CPU. Inference size is 320.

**Key constraint:** YOLO runs on each small crop individually — never on the full frame. Each crop is typically 50–200px wide, so inference is very fast.

**Detection logic:** For each crop, the highest-confidence detection above `_MIN_CONFIDENCE = 0.25` is taken as the representative label. If nothing clears the threshold, the label falls back to `"unknown"`.

**Output:** `List[ClassifiedCrop]` (same order as input):
```python
{
    "region":       str,
    "bbox":         [x1, y1, x2, y2],
    "median_depth": float,
    "label":        str,    # e.g. "person", "chair", "unknown"
    "confidence":   float
}
```

### 5.5 Stage 5 — Decision Engine (`decision_engine.py`)

**Region → motor mapping:**

| Depth region | Motor axis | Physical meaning |
|---|---|---|
| `left`   | `left`  | Obstacle to the user's left |
| `center` | `front` | Obstacle directly ahead |
| `right`  | `right` | Obstacle to the user's right |
| —        | `back`  | Always 0 (no rear sensor) |

**Priority:** The closest obstacle (highest `median_depth` = highest depth value = nearest) fires its motor at intensity `255`. Only one motor fires at a time to avoid confusing the user with simultaneous vibrations.

**Safe command:** If the input list is empty, returns `{"left":0,"front":0,"right":0,"back":0}` immediately.

**Output:** `DecisionResult`:
```python
{
    "motor":     {"left": int, "front": int, "right": int, "back": int},
    "obstacles": [ObstacleSummary, ...]   # priority-sorted, for /stats logging
}
```


---

## 6. Shared State and Locking

All shared state lives in `globals.py`. Nothing else in the backend imports from each other's mutable state — all cross-thread communication goes through this single module.

### 6.1 Frame Slot

```python
latest_frame: Optional[np.ndarray]   # the most recent decoded BGR frame
frame_lock:   threading.Lock         # protects latest_frame pointer
frame_event:  threading.Event        # wakes the AI worker when a new frame lands
```

**Write path (FastAPI coroutine on event loop):**
1. Acquire `frame_lock`.
2. Overwrite `latest_frame` (old frame is garbage-collected).
3. Release `frame_lock`.
4. Call `frame_event.set()`.

**Read path (AI worker thread):**
1. Block on `frame_event.wait(timeout=0.1)`.
2. Acquire `frame_lock`.
3. Copy the pointer, set `latest_frame = None`, clear `frame_event`.
4. Release `frame_lock`.
5. Process the frame (lock is NOT held during inference).

The lock is held for a pointer swap only — never during I/O or inference. Contention is measured in microseconds.

### 6.2 Command Slot

```python
latest_command: dict                 # {"left": 0, "front": 0, "right": 0, "back": 0}
command_lock:   threading.Lock       # protects latest_command
```

**Write path (AI worker, after inference):** Acquire lock → `dict.update(motor)` → release lock.

**Read path (FastAPI coroutine, GET /command):** Acquire lock → `dict(latest_command)` shallow copy → release lock → return copy.

### 6.3 Performance Counters

```python
perf_lock: threading.Lock
_perf: dict  # accumulation counters + published snapshot
```

Three helper functions, all thread-safe:

| Function | Called by | Effect |
|---|---|---|
| `record_receive()` | `POST /receive` | Increments `receive_count` |
| `record_inference(elapsed)` | `worker._ai_worker()` | Increments `ai_count`, adds `elapsed` to `inference_time_total` |
| `snapshot_and_reset()` | `worker._stats_printer()` | Computes FPS rates, publishes them, resets accumulators |
| `get_stats()` | `GET /stats` | Returns last published snapshot (no reset) |

---

## 7. Threading Model

```
┌─────────────────────────────────────────────────────────────────┐
│  OS Process: python main.py (uvicorn)                           │
│                                                                 │
│  ┌─────────────────────────────────────┐                        │
│  │  asyncio Event Loop (Thread 0)      │                        │
│  │  • POST /receive  (coroutine)       │                        │
│  │  • GET /command   (coroutine)       │                        │
│  │  • GET /stats     (coroutine)       │                        │
│  │  All return in < 10 ms              │                        │
│  └──────────────┬──────────────────────┘                        │
│                 │ frame_lock + frame_event                       │
│                 ▼                                               │
│  ┌─────────────────────────────────────┐                        │
│  │  Thread 1: ai-worker (daemon)       │                        │
│  │  • blocks on frame_event.wait()     │                        │
│  │  • runs process_frame() sync        │                        │
│  │  • writes command_lock              │                        │
│  └─────────────────────────────────────┘                        │
│                                                                 │
│  ┌─────────────────────────────────────┐                        │
│  │  Thread 2: stats-printer (daemon)   │                        │
│  │  • sleeps 1 s                       │                        │
│  │  • calls snapshot_and_reset()       │                        │
│  │  • prints one line to stdout        │                        │
│  └─────────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

**Why `threading` and not `asyncio`?**

Depth Anything V2 and YOLO are synchronous, blocking, CPU/GPU-bound operations. Running them inside an `async` function on the event loop would stall every HTTP handler while inference completes. A plain OS thread lets the event loop remain fully responsive (< 10 ms per request) while the AI runs independently.

**Why a single AI worker thread?**

The GPU has one context. Two concurrent inference calls would not speed anything up — they would serialise on the GPU anyway, while adding overhead from context switching and memory contention. One worker + one GPU = maximum utilisation.

**Why daemon threads?**

If uvicorn is killed (Ctrl+C, SIGTERM), daemon threads are automatically killed with the process. The `stop_event` provides a clean, graceful path for the lifespan shutdown hook.


---

## 8. API Contract

### POST /receive

Upload a single JPEG frame for processing.

```
POST http://<server>:8000/receive
Content-Type: multipart/form-data

field name: image
file name:  frame.jpg
MIME type:  image/jpeg
```

**Success response (HTTP 200):**
```json
{"status": "ok"}
```

**Error responses:**
| Code | Meaning |
|---|---|
| 400 | Empty file body |
| 415 | Not a JPEG |
| 422 | JPEG could not be decoded |

### GET /command

Poll for the latest motor command. Intended for the ESP32.

```
GET http://<server>:8000/command
```

**Response (HTTP 200):**
```json
{
    "left":  0,
    "front": 255,
    "right": 0,
    "back":  0
}
```

Values are `0` (motor off) or `255` (motor on at full intensity). Only one axis is non-zero at any given time.

### GET /stats

Developer / monitoring endpoint. Returns rolling 1-second performance metrics.

```
GET http://<server>:8000/stats
```

**Response (HTTP 200):**
```json
{
    "receive_fps":      28.0,
    "ai_fps":           12.3,
    "avg_inference_ms": 81.2
}
```

---

## 9. Performance Design

### 9.1 Frame Drop Policy

The system is designed to drop frames rather than queue them. Latency is the primary metric; coverage is secondary.

| Layer | Drop mechanism |
|---|---|
| CameraX | `STRATEGY_KEEP_ONLY_LATEST` — automatically drops frames when analyzer is busy |
| CameraManager | 66 ms throttle gate — skips frames faster than 15 FPS |
| FrameUploader | `AtomicBoolean` semaphore — drops frame if previous upload not complete |
| Backend frame slot | Pointer overwrite — new frame always replaces old one |

### 9.2 Early Exit Optimisation

The most expensive operation is YOLO. It is skipped entirely on clear frames:

```
Depth only (no obstacle):  ~40–80 ms   (Depth Anything V2 only)
Depth + YOLO (obstacle):   ~80–150 ms  (+ YOLO on small crop)
```

On a typical indoor scene where the path is clear, YOLO never runs. This keeps average inference latency well below the 15 FPS frame interval (~67 ms).

### 9.3 GPU Optimisations

- Depth Anything V2 runs at fp16 on CUDA (half the memory bandwidth, ~2× throughput vs fp32).
- YOLO runs at fp16 on CUDA via `half=True`.
- Both models are loaded once at startup and never reloaded.
- Inference resolution is kept small (384 for depth, 320 for YOLO) to maximise FPS.
- `torch.no_grad()` prevents gradient graph allocation during inference.

### 9.4 Memory Optimisations (Android)

- Pre-allocated `ByteArray` for NV21 conversion — no per-frame allocation.
- Reusable `ByteArrayOutputStream` for JPEG compression — no per-frame allocation.
- Bitmaps recycled immediately after JPEG encoding.
- `ImageProxy.close()` called before the network call — releases sensor buffer ASAP.
- Crop slices from NumPy are views, not copies — no extra VRAM allocated.

### 9.5 Performance Stats Output

The stats printer logs to stdout every second:
```
[HapticGuide]  Recv: 28.0 fps  |  AI: 12.3 fps  |  Inference:  81.2 ms avg
```

- **Recv FPS** = how fast the Android app is uploading frames.
- **AI FPS** = how fast the backend is completing inference passes.
- **Inference ms** = mean wall-clock time of `process_frame()` per cycle.

If `Recv FPS >> AI FPS`, the AI is the bottleneck. If `Recv FPS ≈ AI FPS`, they are in balance.


---

## 10. Build Configuration

### 10.1 Android

| Property | Value | Reason |
|---|---|---|
| AGP | 9.0.1 | First AGP version requiring Gradle 9.1, has built-in Kotlin |
| Gradle | 9.1 | First Gradle version supporting Java 25 (IDE JVM) |
| KGP | 2.2.10 | Bundled by AGP 9.0; no separate declaration needed |
| Compose Compiler | 2.2.10 | Must match KGP version exactly |
| `compileSdk` | 36 | Maximum supported by AGP 9.0 |
| `targetSdk` | 36 | Matches compileSdk |
| `minSdk` | 26 | Android 8.0+ required for CameraX 1.4 |
| Java source/target | 11 | Explicit in `compileOptions`; AGP 9 default is also 11 |

**AGP 9.0 built-in Kotlin:** The `org.jetbrains.kotlin.android` plugin is never applied. AGP 9.0 compiles Kotlin sources natively. The `kotlin.plugin.compose` plugin is still declared explicitly to pin the Compose compiler version.

**No machine-specific paths** in `gradle.properties` or `local.properties`. The IDE resolves the JDK via `.idea/gradle.xml` macros.

### 10.2 Backend Python Dependencies

```
fastapi          HTTP framework
uvicorn          ASGI server
opencv-python    JPEG decode (cv2.imdecode), image ops
torch            GPU tensor operations, model inference
transformers     Depth Anything V2 model + processor (HuggingFace)
ultralytics      YOLOv8n model
numpy            Array operations, depth map processing
Pillow           PIL Image conversion for HuggingFace processor
```

---

## 11. Module Dependency Map

### Backend

```
main.py
 ├── worker.py
 │    └── ai_pipeline.py
 │         ├── depth_pipeline.py        (torch, transformers)
 │         ├── depth_obstacle_detector.py (numpy)
 │         ├── crop_generator.py        (cv2, numpy)
 │         ├── yolo_classifier.py       (ultralytics, torch)
 │         └── decision_engine.py
 ├── routes.py
 │    └── globals.py
 └── globals.py
```

### Android

```
MainActivity
 ├── CameraManager
 │    ├── FrameUploader
 │    └── SettingsManager
 └── SettingsManager
```

---

## 12. Key Design Decisions

### Depth-first, YOLO-on-demand

**Old approach:** Run YOLO on every full frame → get bounding boxes → look up depth at each box centroid → decide.

**Problem:** YOLO on a full 416×416 frame is slow (~100 ms). Running it unconditionally meant the system was always at maximum latency, even on frames where the path was completely clear.

**New approach:** Run depth on every frame (fast, ~40 ms). YOLO only runs when depth has already confirmed an obstacle exists, and only on the small cropped region around that obstacle.

**Result:** Clear-path frames are processed in ~40 ms. Obstacle frames take ~80–150 ms. Average latency drops significantly in real-world use where clear frames are the majority.

### Latest-wins frame slot (no queue)

A queue would guarantee that every frame gets processed, but it would introduce compounding latency — if inference takes 100 ms and frames arrive at 15 FPS (67 ms interval), the queue grows faster than it drains.

By always overwriting the slot with the latest frame, the system processes only the most current information available. Dropped frames are invisible to the user because the motor state is updated continuously.

### HTTP over WebSocket for frame upload

HTTP `POST` is stateless and trivially recoverable from network hiccups. The Android `OkHttpClient` reconnects automatically on failure with no code changes.

WebSocket would require explicit connection management, reconnect logic, and keepalive handling — added complexity for no throughput benefit on a local Wi-Fi network.

### One uvicorn worker

Multiple uvicorn workers would each spawn their own AI thread and attempt to use the same GPU simultaneously. GPU context switching overhead would negate any benefit, and VRAM would be exhausted by duplicate model copies. One process, one GPU, one worker thread.

### threading.Lock not asyncio.Lock

The AI worker is a plain OS thread, not a coroutine. `asyncio.Lock` can only be acquired from within an `async` context. `threading.Lock` works from both coroutines (acquired for microseconds) and threads (acquired during the frame swap). Using `threading.Lock` everywhere avoids the risk of accidentally blocking the event loop with a mutex wait.

---

*End of architecture document.*
