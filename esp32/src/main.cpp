/*
 * main.cpp — PlatformIO entry point for HapticGuide ESP32 Controller
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ---------------------------------------------------------------------------
// Config & Constants
// ---------------------------------------------------------------------------
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_CMD_URL = "http://192.168.1.100:8000/cmd";

const unsigned long POLL_INTERVAL_MS = 40;
const unsigned long HTTP_TIMEOUT_MS  = 150;

#define PIN_MOTOR_LEFT   12
#define PIN_MOTOR_FRONT  13
#define PIN_MOTOR_RIGHT  14
#define PIN_MOTOR_BACK   27

#define PWM_FREQ         5000
#define PWM_RESOLUTION   8

#define CHANNEL_LEFT     0
#define CHANNEL_FRONT    1
#define CHANNEL_RIGHT    2
#define CHANNEL_BACK     3

struct MotorCommand {
    int left  = 0;
    int front = 0;
    int right = 0;
    int back  = 0;
};

static MotorCommand currentCmd;
static unsigned long lastPollTime = 0;

static HTTPClient http;
static WiFiClient wifiClient;

static void initMotorPWM(int pin, int channel) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
    ledcAttach(pin, PWM_FREQ, PWM_RESOLUTION);
#else
    ledcSetup(channel, PWM_FREQ, PWM_RESOLUTION);
    ledcAttachPin(pin, channel);
#endif
}

static void writeMotorPWM(int pin, int channel, int dutyCycle) {
    dutyCycle = max(0, min(255, dutyCycle));
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
    ledcWrite(pin, dutyCycle);
#else
    ledcWrite(channel, dutyCycle);
#endif
}

static void applyMotorCommands(const MotorCommand& cmd, const String& rawJsonPayload) {
    writeMotorPWM(PIN_MOTOR_LEFT,  CHANNEL_LEFT,  cmd.left);
    writeMotorPWM(PIN_MOTOR_FRONT, CHANNEL_FRONT, cmd.front);
    writeMotorPWM(PIN_MOTOR_RIGHT, CHANNEL_RIGHT, cmd.right);
    writeMotorPWM(PIN_MOTOR_BACK,  CHANNEL_BACK,  cmd.back);

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

static void applyFailSafe() {
    MotorCommand offCmd;
    applyMotorCommands(offCmd, "{\"left\":0,\"front\":0,\"right\":0,\"back\":0} (FAILSAFE)");
}

static void pollCommandEndpoint() {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[ESP32] Wi-Fi disconnected. Triggering fail-safe.");
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
            Serial.print("[ESP32] JSON Parsing error: ");
            Serial.println(error.f_str());
            applyFailSafe();
        }
    } else {
        Serial.print("[ESP32] HTTP GET Error: ");
        Serial.println(httpCode);
        applyFailSafe();
    }

    http.end();
}

void setup() {
    Serial.begin(115200);
    delay(500);

    Serial.println();
    Serial.println("==========================================");
    Serial.println("    HapticGuide ESP32 (PlatformIO)       ");
    Serial.println("==========================================");

    initMotorPWM(PIN_MOTOR_LEFT,  CHANNEL_LEFT);
    initMotorPWM(PIN_MOTOR_FRONT, CHANNEL_FRONT);
    initMotorPWM(PIN_MOTOR_RIGHT, CHANNEL_RIGHT);
    initMotorPWM(PIN_MOTOR_BACK,  CHANNEL_BACK);

    applyFailSafe();

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    while (WiFi.status() != WL_CONNECTED) {
        delay(250);
        Serial.print(".");
    }

    Serial.println();
    Serial.print("[ESP32] Wi-Fi Connected. IP: ");
    Serial.println(WiFi.localIP());
    Serial.println("==========================================");
}

void loop() {
    unsigned long now = millis();
    if (now - lastPollTime >= POLL_INTERVAL_MS) {
        lastPollTime = now;
        pollCommandEndpoint();
    }
}
