package com.hapticguide.navigation

import android.util.Log
import com.hapticguide.serial.HapticSerialTransport
import com.hapticguide.serial.StubSerialTransport

/**
 * Handles incoming navigation decision events dynamically from the authoritative navigation source.
 * Dispatches phone haptics to PhoneHapticPlayer and serial commands ("LEFT\n", "RIGHT\n", "START\n", "FRONT\n", "ARRIVAL\n")
 * to HapticSerialTransport.
 *
 * Enforces maneuver deduplication so that continuous GPS poll updates do not re-trigger the same haptic pulses.
 */
class NavigationEventHandler(
    private val phoneHapticPlayer: PhoneHapticPlayer,
    private val serialTransport: HapticSerialTransport = StubSerialTransport(),
) {

    companion object {
        private const val TAG = "NavigationEventHandler"
    }

    @Volatile private var lastHandledEventKey: String? = null
    @Volatile private var startSessionEmitted: Boolean = false

    /**
     * Process a high-level navigation decision snapshot from the authoritative backend.
     * Prevents duplicate transmissions across continuous GPS fixes.
     */
    fun handleDecision(decision: NavigationDecision) {
        val event = decision.pendingHapticEvent ?: return

        // Form unique key for maneuver deduplication across GPS ticks
        val eventKey = "${decision.currentInstruction ?: ""}|${decision.nextInstruction ?: ""}|${event.eventName}"

        if (eventKey == lastHandledEventKey) {
            return  // Deduplicated: already handled this event instance
        }
        lastHandledEventKey = eventKey

        // Once-per-session safeguard for NAVIGATION_START
        if (event == NavigationEvent.START) {
            if (startSessionEmitted) return
            startSessionEmitted = true
        }

        dispatchNavigationEvent(event)
    }

    /**
     * Process an authoritative navigation event directly.
     */
    fun handleEvent(event: NavigationEvent) {
        val key = "DIRECT_${event.eventName}"
        if (key == lastHandledEventKey) return
        lastHandledEventKey = key

        if (event == NavigationEvent.START) {
            if (startSessionEmitted) return
            startSessionEmitted = true
        }

        dispatchNavigationEvent(event)
    }

    private fun dispatchNavigationEvent(event: NavigationEvent) {
        Log.i(TAG, "NAV EVENT: ${event.eventName}")

        when (event) {
            NavigationEvent.START -> {
                // User requested ONLY F:255 haptics. Disabling start pulse.
                // phoneHapticPlayer.handleHapticEvent("NAVIGATION_START")
                serialTransport.send("START")
            }
            NavigationEvent.LEFT -> {
                // Contract: LEFT triggers belt-left motor (GPIO 27)
                serialTransport.send("LEFT")
            }
            NavigationEvent.RIGHT -> {
                // Contract: RIGHT triggers belt-right motor (GPIO 26)
                serialTransport.send("RIGHT")
            }
            NavigationEvent.FRONT -> {
                // User requested ONLY F:255 haptics. Disabling navigation front haptics.
                // phoneHapticPlayer.handleHapticEvent("NAVIGATION_FRONT")
                serialTransport.send("FRONT")
            }
            NavigationEvent.ARRIVAL -> {
                // Contract: ARRIVAL triggers serial arrival command
                serialTransport.send("ARRIVAL")
            }
        }
    }

    /**
     * Reset tracked event state and deduplication cache when navigation session ends or resets.
     */
    fun reset() {
        lastHandledEventKey = null
        startSessionEmitted = false
        serialTransport.send("STOP")
    }
}
