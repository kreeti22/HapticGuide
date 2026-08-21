# ESP32 Haptic Motor Controller Firmware

Dedicated haptic actuator firmware for the HapticGuide navigation system.

---

## 1. Architectural Role

* **Pure Actuator**: The ESP32 does **NOT** run navigation, GPS, route planning, Groq STT, or AI object detection.
* **Responsibilities**:
  1. Ingest line-delimited ASCII commands from `Serial` at **115200 baud**.
  2. Execute haptic pulse waveforms on 2 vibration motors via ESP32 **LEDC PWM** using the **Arduino-ESP32 Core 3.x API**.

---

## 2. Hardware Pinout & Wiring

| Motor | Belt Axis | ESP32 Pin | Default State | PWM Frequency | PWM Resolution |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Motor 1** | Left Motor | `GPIO 27` | `OFF (0 duty)` | `5 kHz` | `8-bit (0–255)` |
| **Motor 2** | Right Motor | `GPIO 26` | `OFF (0 duty)` | `5 kHz` | `8-bit (0–255)` |
| **GND** | Motor Driver GND | `GND` | Common Ground | — | — |

---

## 3. Command Protocol (Line-Delimited ASCII)

| Command | Action | Pattern Details |
| :--- | :--- | :--- |
| `START\n` | Pulse Motor 1 & Motor 2 | 3 pulses (80ms ON, 80ms OFF @ 255 PWM) |
| `LEFT\n` | Pulse Motor 1 (GPIO 27) | 2 pulses (80ms ON, 80ms OFF @ 255 PWM) |
| `RIGHT\n` | Pulse Motor 2 (GPIO 26) | 2 pulses (80ms ON, 80ms OFF @ 255 PWM) |
| `FRONT\n` | Log / Phone primary | Phone internal vibrator handles FRONT per contract; belt motors remain OFF |
| `ARRIVAL\n`| Destination reached | Placeholder; all motors OFF |
| `STOP\n` | Immediate emergency off | Instantly shuts off all motor PWMs and aborts active sequences |

---

## 4. Arduino-ESP32 Core 3.x LEDC API

This firmware strictly uses the modern pin-based LEDC API:
```cpp
// Setup pin for PWM
ledcAttach(PIN_MOTOR_LEFT, 5000, 8);

// Write duty cycle (0-255)
ledcWrite(PIN_MOTOR_LEFT, 255);
```

---

## 5. Build & Upload Instructions

### Arduino IDE
1. Open [`esp32_haptic_guide.ino`](file:///c:/Users/Lenovo/Desktop/HapticGuide/esp32/esp32_haptic_guide.ino).
2. Select Board: **ESP32 Dev Module** (or your specific ESP32 board).
3. Ensure **esp32 by Espressif Systems** package version is **3.x** in Boards Manager.
4. Select Port and click **Upload**.
5. Open Serial Monitor at **115200 baud** to test sending `LEFT`, `RIGHT`, `START`, `STOP`.

### PlatformIO
1. Open the project root or `esp32` folder in VS Code / PlatformIO.
2. Run `pio run --target upload`.
