# ESP32 Haptic Controller Integration

Firmware integration for driving 4-axis haptic vibration motors on ESP32 by polling the HapticGuide backend `GET /cmd` endpoint.

---

## Hardware Pinouts

| Axis | ESP32 GPIO Pin | LEDC Channel | Frequency | Resolution |
| :--- | :--- | :--- | :--- | :--- |
| **Left Motor** | `GPIO 12` | `Channel 0` | 5 kHz | 8-bit (0–255) |
| **Front Motor** | `GPIO 13` | `Channel 1` | 5 kHz | 8-bit (0–255) |
| **Right Motor** | `GPIO 14` | `Channel 2` | 5 kHz | 8-bit (0–255) |
| **Back Motor** | `GPIO 27` | `Channel 3` | 5 kHz | 8-bit (0–255) |

---

## Execution Flow

1. **Wi-Fi Setup**: Connects to the local network in STA mode.
2. **Polling Gate**: Non-blocking `millis()` loop polls `GET /cmd` every **30–50 ms** (~25 Hz).
3. **JSON Parsing**: Parses the 4-axis motor command payload:
   ```json
   {
     "left": 0,
     "front": 255,
     "right": 0,
     "back": 0
   }
   ```
4. **PWM Generation**: Applies PWM intensity `0–255` directly to each motor pin.
5. **Serial Telemetry**: Outputs received command, applied PWM values, and motor ON/OFF states at `115200` baud.
6. **Fail-safe Safety**: Automatically sets all PWM pins to `0` if Wi-Fi disconnects, HTTP fails, or JSON parsing errors occur.

---

## Serial Output Format

```text
==================================================
Received Command : {"left":0,"front":255,"right":0,"back":0}
Applied PWM      : Left=0 | Front=255 | Right=0 | Back=0
Motor States     : Left:OFF | Front:ON (255) | Right:OFF | Back:OFF
==================================================
```

---

## Build Instructions

### Arduino IDE
1. Open [`esp32_haptic_guide.ino`](file:///c:/Users/Utkar/OneDrive/Desktop/HapticGuide/esp32/esp32_haptic_guide.ino).
2. Install the **ArduinoJson** library (`v6.x` or `v7.x`) via Library Manager.
3. Update `WIFI_SSID`, `WIFI_PASSWORD`, and `SERVER_CMD_URL` with your server's IP address.
4. Select Board `ESP32 Dev Module` and click **Upload**.

### PlatformIO
1. Open the `esp32` directory in VS Code / PlatformIO.
2. Update `WIFI_SSID`, `WIFI_PASSWORD`, and `SERVER_CMD_URL` in [`src/main.cpp`](file:///c:/Users/Utkar/OneDrive/Desktop/HapticGuide/esp32/src/main.cpp).
3. Run `pio run --target upload`.
