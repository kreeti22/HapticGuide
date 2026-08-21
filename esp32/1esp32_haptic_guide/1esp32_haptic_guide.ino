/*
 * ==============================================================================
 * HapticGuide ESP32 Motor Controller Firmware
 * ==============================================================================
 * 
 * Hardware Role:
 *   - Dedicated haptic actuator slave.
 *   - Reads newline-delimited commands from Serial (115200 baud).
 *   - Drives 2 haptic vibration motors via ESP32 LEDC PWM.
 *   - Strictly contains NO navigation, routing, GPS, or AI logic.
 * 
 * Target Hardware:
 *   - ESP32 Development Board (ESP32-WROOM-32, NodeMCU-32S, ESP32-S2/S3)
 *   - Motor 1 (Left):  GPIO 27
 *   - Motor 2 (Right): GPIO 26
 * 
 * LEDC PWM API:
 *   - Uses Arduino-ESP32 Core 3.x API:
 *       ledcAttach(pin, frequency, resolution)
 *       ledcWrite(pin, duty)
 * 
 * Command Protocol (ASCII, Line-Delimited):
 *   - START\n    -> 3 pulses on Motor 1 & Motor 2
 *   - LEFT\n     -> 2 pulses on Motor 1 (GPIO 27)
 *   - RIGHT\n    -> 2 pulses on Motor 2 (GPIO 26)
 *   - FRONT\n    -> Safely handled according to contract (Phone vibrator primary)
 *   - ARRIVAL\n  -> Navigation complete placeholder; all motors OFF
 *   - STOP\n     -> Immediately stop all motors
 * ==============================================================================
 */

#include <Arduino.h>

// ------------------------------------------------------------------------------
// Hardware Pin Definitions
// ------------------------------------------------------------------------------
const uint8_t PIN_MOTOR_LEFT  = 27;  // Motor 1 (Left axis)
const uint8_t PIN_MOTOR_RIGHT = 26;  // Motor 2 (Right axis)
const uint8_t PIN_LED_BUILTIN = 2;   // ESP32 Onboard Status LED (GPIO 2)

// ------------------------------------------------------------------------------
// Serial Configuration
// ------------------------------------------------------------------------------
const uint32_t SERIAL_BAUD_RATE = 115200;

// ------------------------------------------------------------------------------
// PWM Parameters (Arduino-ESP32 Core 3.x LEDC)
// ------------------------------------------------------------------------------
const uint32_t PWM_FREQUENCY_HZ  = 5000;  // 5 kHz optimal for haptic drivers
const uint8_t  PWM_RESOLUTION_BITS = 8;   // 8-bit resolution (0 - 255)
const uint32_t PWM_DUTY_MAX       = 150;  // PWM value 150 for both motors
const uint32_t PWM_DUTY_OFF       = 0;    // Motor off

// ------------------------------------------------------------------------------
// Haptic Timing Specifications (Contract Phase 0)
// ------------------------------------------------------------------------------
const uint16_t PULSE_ON_DURATION_MS  = 80;  // Active vibration duration
const uint16_t PULSE_OFF_DURATION_MS = 80;  // Inter-pulse pause duration

const uint8_t PULSE_COUNT_START    = 3;  // START event: 3 pulses
const uint8_t PULSE_COUNT_MANEUVER = 2;  // LEFT / RIGHT events: 2 pulses

// FRONT event behavior:
const bool FRONT_PULSE_MOTORS = false;

// ------------------------------------------------------------------------------
// Non-Blocking Pulse Sequencer State Machine
// ------------------------------------------------------------------------------
struct HapticSequencer {
    bool          isRunning;
    bool          driveMotorLeft;
    bool          driveMotorRight;
    uint8_t       totalPulses;
    uint8_t       currentPulse;
    bool          inOnPhase;
    unsigned long phaseStartTimeMs;
    uint16_t      onDurationMs;
    uint16_t      offDurationMs;
    uint32_t      activeDuty;
};

static HapticSequencer sequencer = {
    false, false, false, 0, 0, false, 0,
    PULSE_ON_DURATION_MS, PULSE_OFF_DURATION_MS, PWM_DUTY_MAX
};

// ------------------------------------------------------------------------------
// Serial Buffer & Activity Tracking
// ------------------------------------------------------------------------------
const size_t RX_BUFFER_CAPACITY = 64;
static char   rxBuffer[RX_BUFFER_CAPACITY];
static size_t rxIndex = 0;
static unsigned long lastSerialRxMs = 0;

void blinkStatusLed(uint8_t times = 1, uint16_t delayMs = 50) {
    for (uint8_t i = 0; i < times; i++) {
        digitalWrite(PIN_LED_BUILTIN, LOW);
        delay(delayMs);
        digitalWrite(PIN_LED_BUILTIN, HIGH);
        delay(delayMs);
    }
}

// ------------------------------------------------------------------------------
// Low-Level Motor Control (Arduino-ESP32 Core 3.x API)
// ------------------------------------------------------------------------------
void setMotorOutputs(uint32_t leftDuty, uint32_t rightDuty) {
    ledcWrite(PIN_MOTOR_LEFT,  leftDuty);
    ledcWrite(PIN_MOTOR_RIGHT, rightDuty);
}

void stopAllMotors() {
    sequencer.isRunning = false;
    setMotorOutputs(PWM_DUTY_OFF, PWM_DUTY_OFF);
}

// ------------------------------------------------------------------------------
// Pulse Sequencer Engine
// ------------------------------------------------------------------------------
void triggerHapticSequence(bool left, bool right, uint8_t pulses, uint16_t onMs, uint16_t offMs, uint32_t duty) {
    if (pulses == 0 || (!left && !right)) {
        stopAllMotors();
        return;
    }

    sequencer.driveMotorLeft   = left;
    sequencer.driveMotorRight  = right;
    sequencer.totalPulses      = pulses;
    sequencer.currentPulse     = 1;
    sequencer.inOnPhase        = true;
    sequencer.onDurationMs     = onMs;
    sequencer.offDurationMs    = offMs;
    sequencer.activeDuty       = duty;
    sequencer.phaseStartTimeMs = millis();
    sequencer.isRunning        = true;

    // Apply immediate ON phase
    setMotorOutputs(
        left  ? duty : PWM_DUTY_OFF,
        right ? duty : PWM_DUTY_OFF
    );
}

void updateHapticSequencer() {
    if (!sequencer.isRunning) return;

    unsigned long now = millis();
    unsigned long elapsed = now - sequencer.phaseStartTimeMs;

    if (sequencer.inOnPhase) {
        if (elapsed >= sequencer.onDurationMs) {
            setMotorOutputs(PWM_DUTY_OFF, PWM_DUTY_OFF);
            if (sequencer.currentPulse >= sequencer.totalPulses) {
                sequencer.isRunning = false;
            } else {
                sequencer.inOnPhase        = false;
                sequencer.phaseStartTimeMs = now;
            }
        }
    } else {
        if (elapsed >= sequencer.offDurationMs) {
            sequencer.currentPulse++;
            sequencer.inOnPhase        = true;
            sequencer.phaseStartTimeMs = now;

            setMotorOutputs(
                sequencer.driveMotorLeft  ? sequencer.activeDuty : PWM_DUTY_OFF,
                sequencer.driveMotorRight ? sequencer.activeDuty : PWM_DUTY_OFF
            );
        }
    }
}

// ------------------------------------------------------------------------------
// Command Parser & Dispatcher
// ------------------------------------------------------------------------------
void processSerialCommand(const char* rawCommand) {
    while (*rawCommand == ' ' || *rawCommand == '\t' || *rawCommand == '\r' || *rawCommand == '\n') {
        rawCommand++;
    }

    size_t len = strlen(rawCommand);
    while (len > 0 && (rawCommand[len - 1] == ' ' || rawCommand[len - 1] == '\t' || 
                       rawCommand[len - 1] == '\r' || rawCommand[len - 1] == '\n')) {
        len--;
    }

    if (len == 0) return;

    char cmd[32];
    size_t copyLen = (len < sizeof(cmd) - 1) ? len : (sizeof(cmd) - 1);
    strncpy(cmd, rawCommand, copyLen);
    cmd[copyLen] = '\0';

    for (size_t i = 0; i < copyLen; i++) {
        cmd[i] = toupper((unsigned char)cmd[i]);
    }

    lastSerialRxMs = millis();
    Serial.print("RX: ");
    Serial.println(cmd);

    // Flash built-in LED on every serial command received
    digitalWrite(PIN_LED_BUILTIN, LOW);
    delay(20);
    digitalWrite(PIN_LED_BUILTIN, HIGH);

    int l = 0, f = 0, r = 0, b = 0;
    if (sscanf(cmd, "M,%d,%d,%d,%d", &l, &f, &r, &b) == 4) {
        if (l == 0 && f == 0 && r == 0 && b == 0) {
            stopAllMotors();
            Serial.println("[ESP32] OK: STOP");
        } else {
            bool driveL = (l > 0);
            bool driveR = (r > 0);
            uint32_t dutyL = driveL ? (uint32_t)l : 0;
            uint32_t dutyR = driveR ? (uint32_t)r : 0;
            if (driveL || driveR) {
                uint32_t duty = (dutyL > 0) ? dutyL : dutyR;
                triggerHapticSequence(driveL, driveR, 1, PULSE_ON_DURATION_MS, PULSE_OFF_DURATION_MS, duty);
                if (driveL) Serial.println("[ESP32] OK: LEFT MOTOR");
                if (driveR) Serial.println("[ESP32] OK: RIGHT MOTOR");
            }
        }
    }
    else if (strcmp(cmd, "PING") == 0) {
        Serial.println("[ESP32] PONG - Serial Communication Active");
        blinkStatusLed(3, 50);
    }
    else if (strcmp(cmd, "START") == 0) {
        Serial.println("[ESP32] CMD: START -> Pulsing Left & Right motors (3x)");
        triggerHapticSequence(true, true, PULSE_COUNT_START, PULSE_ON_DURATION_MS, PULSE_OFF_DURATION_MS, PWM_DUTY_MAX);
    }
    else if (strcmp(cmd, "LEFT") == 0) {
        Serial.println("[ESP32] CMD: LEFT -> Pulsing Motor 1 (GPIO 27) (2x)");
        triggerHapticSequence(true, false, PULSE_COUNT_MANEUVER, PULSE_ON_DURATION_MS, PULSE_OFF_DURATION_MS, PWM_DUTY_MAX);
    }
    else if (strcmp(cmd, "RIGHT") == 0) {
        Serial.println("[ESP32] CMD: RIGHT -> Pulsing Motor 2 (GPIO 26) (2x)");
        triggerHapticSequence(false, true, PULSE_COUNT_MANEUVER, PULSE_ON_DURATION_MS, PULSE_OFF_DURATION_MS, PWM_DUTY_MAX);
    }
    else if (strcmp(cmd, "FRONT") == 0) {
        Serial.println("[ESP32] CMD: FRONT -> Received (Phone vibrator primary channel)");
        if (FRONT_PULSE_MOTORS) {
            triggerHapticSequence(true, true, PULSE_COUNT_MANEUVER, PULSE_ON_DURATION_MS, PULSE_OFF_DURATION_MS, PWM_DUTY_MAX);
        } else {
            stopAllMotors();
        }
    }
    else if (strcmp(cmd, "ARRIVAL") == 0) {
        Serial.println("[ESP32] CMD: ARRIVAL -> Destination reached. Motors OFF.");
        stopAllMotors();
    }
    else if (strcmp(cmd, "STOP") == 0) {
        Serial.println("[ESP32] CMD: STOP -> All motors disabled immediately");
        stopAllMotors();
    }
    else {
        Serial.print("[ESP32] WARN: Unknown command ignored: \"");
        Serial.print(cmd);
        Serial.println("\"");
    }
}

// ------------------------------------------------------------------------------
// Serial Reader Loop
// ------------------------------------------------------------------------------
void handleSerialInput() {
    while (Serial.available() > 0) {
        char c = (char)Serial.read();

        if (c == '\n' || c == '\r') {
            if (rxIndex > 0) {
                rxBuffer[rxIndex] = '\0';
                processSerialCommand(rxBuffer);
                rxIndex = 0;
            }
        } else {
            if (rxIndex < RX_BUFFER_CAPACITY - 1) {
                rxBuffer[rxIndex++] = c;
            } else {
                Serial.println("[ESP32] WARN: Rx buffer overflow. Discarding line.");
                rxIndex = 0;
            }
        }
    }
}

// ------------------------------------------------------------------------------
// Arduino Setup
// ------------------------------------------------------------------------------
void setup() {
    // 1. Initialize Built-in Status LED (GPIO 2)
    pinMode(PIN_LED_BUILTIN, OUTPUT);
    digitalWrite(PIN_LED_BUILTIN, HIGH);  // Solid ON indicates Serial layer initialized

    // 2. Initialize Serial Interface
    Serial.begin(SERIAL_BAUD_RATE);
    delay(200);

    Serial.println();
    Serial.println("==================================================");
    Serial.println("       HapticGuide ESP32 Motor Controller         ");
    Serial.println("       Arduino-ESP32 Core 3.x LEDC Driver         ");
    Serial.println("==================================================");

    // 3. Initialize GPIOs for PWM via Arduino-ESP32 Core 3.x LEDC API
    bool leftAttached  = ledcAttach(PIN_MOTOR_LEFT,  PWM_FREQUENCY_HZ, PWM_RESOLUTION_BITS);
    bool rightAttached = ledcAttach(PIN_MOTOR_RIGHT, PWM_FREQUENCY_HZ, PWM_RESOLUTION_BITS);

    Serial.print("[ESP32] Motor 1 (Left)  -> GPIO ");
    Serial.print(PIN_MOTOR_LEFT);
    Serial.println(leftAttached ? " [OK]" : " [ATTACH FAILED]");

    Serial.print("[ESP32] Motor 2 (Right) -> GPIO ");
    Serial.print(PIN_MOTOR_RIGHT);
    Serial.println(rightAttached ? " [OK]" : " [ATTACH FAILED]");

    stopAllMotors();

    // Blink onboard LED 3 times to signal boot completed & ready
    blinkStatusLed(3, 80);

    Serial.println("[ESP32] Ready. Listening for serial commands...");
    Serial.println("==================================================");
}

// ------------------------------------------------------------------------------
// Main Execution Loop
// ------------------------------------------------------------------------------
void loop() {
    handleSerialInput();
    updateHapticSequencer();
}
