package com.hapticguide.serial

import android.content.Context
import android.util.Log
import com.hapticguide.navigation.NavigationEvent
import kotlinx.coroutines.flow.StateFlow

/**
 * High-level manager orchestrating serial communication to the ESP32 belt.
 *
 * Responsibilities:
 * - Selects active transport (UsbSerialTransport if USB OTG available, fallback to StubSerialTransport)
 * - Exposes connectionState
 * - Dispatches line-delimited commands
 * - Provides manual test/debug methods to test haptic pulses without requiring a full live GPS session
 */
class HapticSerialManager(context: Context) : HapticSerialTransport {

    companion object {
        private const val TAG = "HapticSerialManager"
    }

    private val usbTransport = UsbSerialTransport(context)
    private val stubTransport = StubSerialTransport()

    // Defaults to USB transport; delegates to stub if USB not attached or fails
    override val connectionState: StateFlow<SerialConnectionState>
        get() = if (usbTransport.isConnected()) usbTransport.connectionState else stubTransport.connectionState

    override fun connect(): Boolean {
        val usbOk = usbTransport.connect()
        if (usbOk) {
            Log.i(TAG, "Connected via USB OTG Serial")
            return true
        }
        Log.i(TAG, "USB device not available; using Stub serial transport")
        return stubTransport.connect()
    }

    override fun disconnect() {
        usbTransport.disconnect()
        stubTransport.disconnect()
    }

    override fun send(command: String): Boolean {
        val cleanCmd = command.trim()
        if (cleanCmd.isEmpty()) return false

        return if (usbTransport.isConnected()) {
            usbTransport.send(cleanCmd)
        } else {
            stubTransport.send(cleanCmd)
        }
    }

    override fun sendEvent(event: NavigationEvent): Boolean {
        val cmd = when (event) {
            NavigationEvent.START -> "START"
            NavigationEvent.LEFT -> "LEFT"
            NavigationEvent.RIGHT -> "RIGHT"
            NavigationEvent.FRONT -> "FRONT"
            NavigationEvent.ARRIVAL -> "ARRIVAL"
        }
        return send(cmd)
    }

    override fun isConnected(): Boolean {
        return usbTransport.isConnected() || stubTransport.isConnected()
    }

    // ── Manual Test / Debug Helpers ──────────────────────────────────────────

    fun testStart(): Boolean = send("START")
    fun testLeft(): Boolean = send("LEFT")
    fun testRight(): Boolean = send("RIGHT")
    fun testFront(): Boolean = send("FRONT")
    fun testArrival(): Boolean = send("ARRIVAL")
    fun testStop(): Boolean = send("STOP")
    fun testRawMotorCommand(left: Int, front: Int, right: Int, back: Int): Boolean {
        return send("M,$left,$front,$right,$back")
    }

    fun shutdown() {
        usbTransport.unregister()
    }
}
