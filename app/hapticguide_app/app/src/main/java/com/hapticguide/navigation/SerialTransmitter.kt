package com.hapticguide.navigation

import android.util.Log
import com.hapticguide.serial.HapticSerialTransport
import com.hapticguide.serial.StubSerialTransport

/**
 * Interface defining the serial command abstraction for communicating with the ESP32.
 * Backed by HapticSerialTransport.
 */
interface SerialTransmitter {
    fun sendMotorCommand(left: Int, front: Int, right: Int, back: Int)
    fun sendNavigationEvent(event: NavigationEvent)
    fun isConnected(): Boolean
}

/**
 * Adapter bridging SerialTransmitter to HapticSerialTransport.
 */
class SerialTransmitterAdapter(
    private val transport: HapticSerialTransport = StubSerialTransport(),
) : SerialTransmitter {

    override fun sendMotorCommand(left: Int, front: Int, right: Int, back: Int) {
        transport.send("M,$left,$front,$right,$back")
    }

    override fun sendNavigationEvent(event: NavigationEvent) {
        transport.sendEvent(event)
    }

    override fun isConnected(): Boolean = transport.isConnected()
}

/**
 * Legacy stub implementation.
 */
class SerialTransmitterStub : SerialTransmitter {
    companion object {
        private const val TAG = "SerialTransmitter"
    }

    @Volatile private var connected = false

    override fun sendMotorCommand(left: Int, front: Int, right: Int, back: Int) {
        val payload = "M,$left,$front,$right,$back\n"
        Log.i(TAG, "SERIAL TRANSMIT MOTOR: $payload".trimEnd())
    }

    override fun sendNavigationEvent(event: NavigationEvent) {
        val payload = "E,${event.eventName}\n"
        Log.i(TAG, "SERIAL TRANSMIT EVENT: $payload".trimEnd())
    }

    override fun isConnected(): Boolean = connected

    fun setConnected(status: Boolean) {
        connected = status
    }
}
