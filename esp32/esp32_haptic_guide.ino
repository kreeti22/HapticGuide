/*
 * HapticGuide ESP32 Motor Controller Firmware
 * ===========================================
 *
 * Responsibilities:
 *   1. Connect to local Wi-Fi network.
 *   2. Poll GET /cmd endpoint from HapticGuide FastAPI backend every 30-50 ms.
 *   3. Parse JSON payload: {"left": int, "front": int, "right": int, "back": int}.
 *   4. Apply PWM (0-255) to 4 haptic vibration motors via ESP32 LEDC PWM peripheral.
 *   5. Log telemetry to Serial (Received Command, Applied PWM, Motor States).
 *   6. Fail-safe protection: set all motor PWMs to 0 if connection drops or response fails.
 *
 * Hardware Wiring (Default GPIOs):
 *   - Left Motor  -> GPIO 12
 *   - Front Motor -> GPIO 13
 *   - Right Motor -> GPIO 14
 *   - Back Motor  -> GPIO 27
 *   - Common GND  -> Power Supply / Motor Driver GND
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ---------------------------------------------------------------------------
// Network & Server Configuration
// ---------------------------------------------------------------------------
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Replace with your backend IP address (e.g. "http://192.168.1.100:8000/cmd")
const char* SERVER_CMD_URL = "http://192.168.1.100:8000/cmd";

// Polling interval gate (30 - 50 ms loop execution)
const unsigned long POLL_INTERVAL_MS = 40;  // ~25 Hz polling rate
const unsigned long HTTP_TIMEOUT_MS = 150;  // Low latency HTTP timeout

// ---------------------------------------------------------------------------
// Hardware Pin & PWM Definitions
// ---------------------------------------------------------------------------
#define PIN_MOTOR_LEFT   12
#define PIN_MOTOR_FRONT  13
#define PIN_MOTOR_RIGHT  14
#define PIN_MOTOR_BACK   27

#define PWM_FREQ         5000  // 5 kHz PWM frequency
#define PWM_RESOLUTION   8     // 8-bit resolution (0 - 255)

#define CHANNEL_LEFT     0
#define CHANNEL_FRONT    1
#define CHANNEL_RIGHT    2
#define CHANNEL_BACK     3

// ---------------------------------------------------------------------------
// State Tracking
// ---------------------------------------------------------------------------
struct MotorCommand {
    int left  = 0;
    int front = 0;
    int right = 0;
    int back  = 0;
};

MotorCommand currentCmd;
unsigned long lastPollTime = 0;

// Shared HTTPClient instance for HTTP keep-alive connection reuse
HTTPClient http;
WiFiClient wifiClient;

// ---------------------------------------------------------------------------
// Helper: Core-Agnostic LEDC Setup
// ---------------------------------------------------------------------------
void initMotorPWM(int pin, int channel) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
    // Arduino ESP32 Core v3+ API
    ledcAttach(pin, PWM_FREQ, PWM_RESOLUTION);
#else
    // Arduino ESP32 Core v2 API
    ledcSetup(channel, PWM_FREQ, PWM_RESOLUTION);
    ledcAttachPin(pin, channel);
#endif
}

void writeMotorPWM(int pin, int channel, int dutyCycle) {
    // Clamp duty cycle to valid 8-bit range [0, 255]
    dutyCycle = max(0, min(255, dutyCycle));

#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
    ledcWrite(pin, dutyCycle);
#else
    ledcWrite(channel, dutyCycle);
#endif
}

// ---------------------------------------------------------------------------
// Apply Motor PWM & Output Serial Telemetry
// ---------------------------------------------------------------------------
void applyMotorCommands(const MotorCommand& cmd, const String& rawJsonPayload) {
    // 1. Drive Hardware PWM Outputs
    writeMotorPWM(PIN_MOTOR_LEFT,  CHANNEL_LEFT,  cmd.left);
    writeMotorPWM(PIN_MOTOR_FRONT, CHANNEL_FRONT, cmd.front);
    writeMotorPWM(PIN_MOTOR_RIGHT, CHANNEL_RIGHT, cmd.right);
    writeMotorPWM(PIN_MOTOR_BACK,  CHANNEL_BACK,  cmd.back);

    // 2. Format & Print Telemetry
    Serial.println("==================================================");
    Serial.print("Received Command : ");
    Serial.println(rawJsonPayload.length() > 0 ? rawJsonPayload : "FAILSAFE_OFF");

    Serial.print("Applied PWM      : Left=");
    Serial.print(cmd.left);
    Serial.print(" | Front=");
    Serial.print(cmd.front);
    Serial.print(" | Right=");
    Serial.print(cmd.right);
    Serial.print(" | Back=");
    Serial.println(cmd.back);

    Serial.print("Motor States     : Left:");
    Serial.print(cmd.left > 0 ? "ON (" + String(cmd.left) + ")" : "OFF");
    Serial.print(" | Front:");
    Serial.print(cmd.front > 0 ? "ON (" + String(cmd.front) + ")" : "OFF");
    Serial.print(" | Right:");
    Serial.print(cmd.right > 0 ? "ON (" + String(cmd.right) + ")" : "OFF");
    Serial.print(" | Back:");
    Serial.println(cmd.back > 0 ? "ON (" + String(cmd.back) + ")" : "OFF");
    Serial.println("==================================================");
}

// ---------------------------------------------------------------------------
// Fail-safe Emergency Off
// ---------------------------------------------------------------------------
void applyFailSafe() {
    MotorCommand offCmd;
    applyMotorCommands(offCmd, "{\"left\":0,\"front\":0,\"right\":0,\"back\":0} (FAILSAFE)");
}

// ---------------------------------------------------------------------------
// GET /cmd Poller
// ---------------------------------------------------------------------------
void pollCommandEndpoint() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[ESP32] Wi-Fi connection lost! Engaging fail-safe.");
        applyFailSafe();
        return;
    }

    http.begin(wifiClient, SERVER_CMD_URL);
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.addHeader("Connection", "keep-alive");

    int httpCode = http.GET();

    if (httpCode == HTTP_CODE_OK) {
        String payload = http.getString();
        
        StaticJsonDocument<256> doc;
        DeserializationError error = deserializeJson(doc, payload);

        if (!error) {
            currentCmd.left  = doc["left"]  | 0;
            currentCmd.front = doc["front"] | 0;
            currentCmd.right = doc["right"] | 0;
            currentCmd.back  = doc["back"]  | 0;

            applyMotorCommands(currentCmd, payload);
        } else {
            Serial.print("[ESP32] JSON Parsing Failed: ");
            Serial.println(error.f_str());
            applyFailSafe();
        }
    } else {
        Serial.print("[ESP32] HTTP GET Failed, Code: ");
        Serial.println(httpCode);
        applyFailSafe();
    }

    http.end();
}

// ---------------------------------------------------------------------------
// Arduino Setup & Main Loop
// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(500);

    Serial.println();
    Serial.println("==========================================");
    Serial.println("      HapticGuide ESP32 Firmware          ");
    Serial.println("==========================================");

    // Initialize Motor PWM Pins
    initMotorPWM(PIN_MOTOR_LEFT,  CHANNEL_LEFT);
    initMotorPWM(PIN_MOTOR_FRONT, CHANNEL_FRONT);
    initMotorPWM(PIN_MOTOR_RIGHT, CHANNEL_RIGHT);
    initMotorPWM(PIN_MOTOR_BACK,  CHANNEL_BACK);

    // Initial Failsafe Shutdown
    applyFailSafe();

    // Connect to Wi-Fi
    Serial.print("[ESP32] Connecting to Wi-Fi SSID: ");
    Serial.println(WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    while (WiFi.status() != WL_CONNECTED) {
        delay(250);
        Serial.print(".");
    }

    Serial.println();
    Serial.print("[ESP32] Connected! Local IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("[ESP32] Polling endpoint: ");
    Serial.println(SERVER_CMD_URL);
    Serial.print("[ESP32] Polling interval: ");
    Serial.print(POLL_INTERVAL_MS);
    Serial.println(" ms");
    Serial.println("==========================================");
}

void loop() {
    unsigned long now = millis();
    if (now - lastPollTime >= POLL_INTERVAL_MS) {
        lastPollTime = now;
        pollCommandEndpoint();
    }
}
