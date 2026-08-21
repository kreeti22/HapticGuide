package com.hapticguide.serial

import com.hapticguide.navigation.NavigationEvent
import kotlinx.coroutines.flow.StateFlow

/**
 * Interface defining the serial transport for Android → ESP32 communication.
 *
 * Responsibilities:
 * - connect / disconnect lifecycle
 * - connection state reporting via StateFlow
 * - send line-delimited ASCII commands ("LEFT\n", "RIGHT\n", "START\n", etc.)
 * - send high-level NavigationEvent
 * - handle communication errors gracefully without crashing the app
 */
interface HapticSerialTransport {

    /**
     * Observable connection state.
     */
    val connectionState: StateFlow<SerialConnectionState>

    /**
     * Last message/acknowledgement received from ESP32 over serial.
     */
    val lastRxMessage: StateFlow<String>

    /**
     * Connect to the ESP32 serial interface.
     * @return true if connection succeeded, false otherwise.
     */
    fun connect(): Boolean

    /**
     * Disconnect and release serial port resources.
     */
    fun disconnect()

    /**
     * Send a raw line-delimited command string to the ESP32.
     * Appends '\n' automatically if not present.
     * Logs "SERIAL TX: <COMMAND>".
     * @return true if transmitted successfully, false otherwise.
     */
    fun send(command: String): Boolean

    /**
     * Convenience method to transmit a NavigationEvent directly.
     */
    fun sendEvent(event: NavigationEvent): Boolean

    /**
     * Check if currently connected.
     */
    fun isConnected(): Boolean
}
