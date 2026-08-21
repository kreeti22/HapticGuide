package com.hapticguide.serial

/**
 * Connection states for the Android to ESP32 serial communication layer.
 */
enum class SerialConnectionState(val statusText: String) {
    DISCONNECTED("Disconnected"),
    CONNECTING("Connecting…"),
    CONNECTED("Connected (115200 baud)"),
    ERROR("Serial Error");
}
