package com.hapticguide.navigation

import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
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
open class PhoneHapticPlayer(context: Context? = null) {

    companion object {
        private const val TAG = "PhoneHapticPlayer"

        // NAVIGATION_FRONT: 2 short pulses (80ms on, 80ms off, 80ms on)
        val PATTERN_FRONT = longArrayOf(0, 80, 80, 80)

        // NAVIGATION_LEFT: 1 long pulse (150ms)
        val PATTERN_LEFT = longArrayOf(0, 150)

        // NAVIGATION_RIGHT: 3 quick pulses (40ms on, 40ms off, 40ms on, 40ms off, 40ms on)
        val PATTERN_RIGHT = longArrayOf(0, 40, 40, 40, 40, 40)

        // NAVIGATION_START: 3 pulses (80ms on, 80ms off, 80ms on, 80ms on, 80ms on)
        val PATTERN_START = longArrayOf(0, 80, 80, 80, 80, 80)
    }

    private val vibrator: Vibrator? = if (context != null) {
        @Suppress("DEPRECATION")
        context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    } else null

    private val mainHandler = Handler(Looper.getMainLooper())

    private fun runOnMainThread(action: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            action()
        } else {
            mainHandler.post(action)
        }
    }

    @Volatile private var lastTriggeredEvent: String? = null

    open fun handleHapticEvent(eventType: String?) {
        if (eventType == null || eventType.isEmpty()) {
            lastTriggeredEvent = null
            return
        }
        if (eventType == lastTriggeredEvent) return
        lastTriggeredEvent = eventType

        when (eventType) {
            "NAVIGATION_FRONT" -> playFrontManeuver()
            "NAVIGATION_LEFT" -> playLeftManeuver()
            "NAVIGATION_RIGHT" -> playRightManeuver()
            "NAVIGATION_START" -> playStartPulse()
        }
    }

    /**
     * Version-aware single duration vibration.
     */
    open fun vibratePhone(durationMs: Long = 400L) {
        val v = vibrator
        if (v == null) {
            Log.w(TAG, "Vibrator service is null")
            return
        }
        try {
            runOnMainThread {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    // No AudioAttributes here on purpose — USAGE_ASSISTANCE_NAVIGATION_GUIDANCE
                    // ties vibration to audio focus, which this app's active camera/mic session
                    // was suppressing in the foreground. Plain VibrationEffect always fires.
                    v.vibrate(VibrationEffect.createOneShot(durationMs, VibrationEffect.DEFAULT_AMPLITUDE))
                } else {
                    @Suppress("DEPRECATION")
                    v.vibrate(durationMs)
                }
                Log.i(TAG, "Vibrated phone for ${durationMs}ms")
            }
        } catch (e: Exception) {
            try {
                runOnMainThread {
                    @Suppress("DEPRECATION")
                    v.vibrate(durationMs)
                }
            } catch (ex: Exception) {
                Log.w(TAG, "Failed to vibrate phone: ${ex.message}")
            }
        }
    }

    /**
     * Starts a continuous vibration that keeps running until stopVibration()
     * is called. Uses a long-duration one-shot as a practical "indefinite"
     * vibration (capped at 60s as a safety net in case a stop signal is
     * ever missed, e.g. due to a crash) — always executed on the main
     * thread via runOnMainThread, same as the rest of this class.
     */
    open fun startContinuousVibration() {
        val v = vibrator
        if (v == null) {
            Log.w(TAG, "Vibrator service is null")
            return
        }
        try {
            runOnMainThread {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    v.vibrate(VibrationEffect.createOneShot(60000L, VibrationEffect.DEFAULT_AMPLITUDE))
                } else {
                    @Suppress("DEPRECATION")
                    v.vibrate(60000L)
                }
                Log.i(TAG, "Started continuous vibration")
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to start continuous vibration: ${e.message}")
        }
    }

    /**
     * Version-aware waveform pattern vibration.
     */
    open fun vibratePhonePattern(pattern: LongArray) {
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        try {
            runOnMainThread {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    val effect = VibrationEffect.createWaveform(pattern, -1)
                    // No AudioAttributes here on purpose — USAGE_ASSISTANCE_NAVIGATION_GUIDANCE
                    // ties vibration to audio focus, which this app's active camera/mic session
                    // was suppressing in the foreground. Plain VibrationEffect always fires.
                    v.vibrate(effect)
                } else {
                    @Suppress("DEPRECATION")
                    v.vibrate(pattern, -1)
                }
            }
        } catch (e: Exception) {
            vibratePhone(400L)
        }
    }

    open fun playFrontManeuver() = vibratePhone(400L)
    open fun playLeftManeuver() = vibratePhonePattern(PATTERN_LEFT)
    open fun playRightManeuver() = vibratePhonePattern(PATTERN_RIGHT)
    open fun playStartPulse() = vibratePhonePattern(PATTERN_START)

    open fun playPattern(timings: LongArray) {
        val v = vibrator ?: return
        try {
            runOnMainThread {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    val effect = VibrationEffect.createWaveform(timings, -1)
                    // No AudioAttributes here on purpose — USAGE_ASSISTANCE_NAVIGATION_GUIDANCE
                    // ties vibration to audio focus, which this app's active camera/mic session
                    // was suppressing in the foreground. Plain VibrationEffect always fires.
                    v.vibrate(effect)
                } else {
                    @Suppress("DEPRECATION")
                    v.vibrate(timings, -1)
                }
                Log.i(TAG, "Phone vibration played with ${timings.size / 2} pulses")
            }
        } catch (e: Exception) {
            try {
                runOnMainThread {
                    // Strong 250ms fallback vibration
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        v.vibrate(VibrationEffect.createOneShot(250, VibrationEffect.DEFAULT_AMPLITUDE))
                    } else {
                        @Suppress("DEPRECATION")
                        v.vibrate(250)
                    }
                }
            } catch (ex: Exception) {
                Log.w(TAG, "Failed to vibrate phone: ${ex.message}")
            }
        }
    }

    open fun stopVibration() {
        try {
            runOnMainThread {
                vibrator?.cancel()
            }
        } catch (_: Exception) {}
    }
}
