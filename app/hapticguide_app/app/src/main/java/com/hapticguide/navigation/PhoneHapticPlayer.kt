package com.hapticguide.navigation

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log

/**
 * Dedicated smartphone vibrator controller for navigation feedback.
 *
 * Drives phone-front navigation output (NAVIGATION_FRONT and NAVIGATION_START).
 * Isolated from CameraX, TCP streaming, and ESP32 belt motors.
 */
class PhoneHapticPlayer(context: Context) {

    companion object {
        private const val TAG = "PhoneHapticPlayer"

        // NAVIGATION_FRONT: 2 short pulses (80ms on, 80ms off, 80ms on)
        val PATTERN_FRONT = longArrayOf(0, 80, 80, 80)

        // NAVIGATION_START: 3 pulses (80ms on, 80ms off, 80ms on, 80ms off, 80ms on)
        val PATTERN_START = longArrayOf(0, 80, 80, 80, 80, 80)
    }

    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        val vm = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
        vm?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    }

    @Volatile private var lastTriggeredEvent: String? = null

    fun handleHapticEvent(eventType: String?) {
        if (eventType == null || eventType.isEmpty()) {
            lastTriggeredEvent = null
            return
        }
        if (eventType == lastTriggeredEvent) return
        lastTriggeredEvent = eventType

        when (eventType) {
            "NAVIGATION_FRONT" -> playPattern(PATTERN_FRONT)
            "NAVIGATION_START" -> playPattern(PATTERN_START)
        }
    }

    fun playPattern(timings: LongArray) {
        val v = vibrator ?: return
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val effect = VibrationEffect.createWaveform(timings, -1)
                v.vibrate(effect)
            } else {
                @Suppress("DEPRECATION")
                v.vibrate(timings, -1)
            }
            Log.i(TAG, "Phone vibration played with ${timings.size / 2} pulses")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to vibrate phone: ${e.message}")
        }
    }
}
