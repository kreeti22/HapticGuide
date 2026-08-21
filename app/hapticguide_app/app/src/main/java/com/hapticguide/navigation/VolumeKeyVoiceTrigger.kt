package com.hapticguide.navigation

import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Manages physical dual-button (Volume Up + Volume Down) chord detection for voice input.
 *
 * Requirements:
 * 1. User presses Volume Up + Volume Down at approximately the same time.
 * 2. When both remain held for ~1000ms:
 *    a. Triggers short phone haptic confirmation.
 *    b. Enters RECORDING state and starts microphone recording.
 * 3. While buttons remain held, recording continues.
 * 4. When buttons are released, recording stops and audio is finalized.
 * 5. Consumes volume key events during chord interaction to prevent system volume changes.
 */
class VolumeKeyVoiceTrigger(
    private val voiceRecorder: VoiceRecorder,
    private val phoneHapticPlayer: PhoneHapticPlayer,
    private val coroutineScope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Main),
) {

    companion object {
        private const val TAG = "VOICE"
        const val HOLD_THRESHOLD_MS: Long = 1000L
        const val CHORD_TOLERANCE_MS: Long = 400L
    }

    private val _activationState = MutableStateFlow(VoiceActivationState.IDLE)
    val activationState: StateFlow<VoiceActivationState> = _activationState.asStateFlow()

    @Volatile var isVolUpPressed: Boolean = false
        private set
    @Volatile var isVolDownPressed: Boolean = false
        private set

    private var volUpPressTimeMs: Long = 0L
    private var volDownPressTimeMs: Long = 0L

    private var holdTimerJob: Job? = null
    private var singleKeyTimeoutJob: Job? = null

    /**
     * Intercept key down events. Returns true if the event was handled/consumed.
     */
    fun handleKeyDown(keyCode: Int, repeatCount: Int): Boolean {
        if (keyCode != KeyEvent.KEYCODE_VOLUME_UP && keyCode != KeyEvent.KEYCODE_VOLUME_DOWN) {
            return false
        }

        // Ignore hardware auto-repeat ticks when key is already held
        if (repeatCount > 0) {
            return true
        }

        val now = SystemClock.uptimeMillis()

        when (keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP -> {
                Log.i(TAG, "VOICE: Volume Up detected")
                isVolUpPressed = true
                volUpPressTimeMs = now
            }
            KeyEvent.KEYCODE_VOLUME_DOWN -> {
                Log.i(TAG, "VOICE: Volume Down detected")
                isVolDownPressed = true
                volDownPressTimeMs = now
            }
        }

        // Check if BOTH keys are now pressed
        if (isVolUpPressed && isVolDownPressed) {
            singleKeyTimeoutJob?.cancel()
            singleKeyTimeoutJob = null

            Log.i(TAG, "VOICE: Both buttons held")
            _activationState.value = VoiceActivationState.ARMED

            // Start 1-second hold timer
            holdTimerJob?.cancel()
            holdTimerJob = coroutineScope.launch {
                delay(HOLD_THRESHOLD_MS)

                // Verify both keys are still held after 1s
                if (isVolUpPressed && isVolDownPressed) {
                    _activationState.value = VoiceActivationState.RECORDING

                    // 1. Short phone haptic confirmation
                    phoneHapticPlayer.playPattern(longArrayOf(0, 80))

                    // 2. Start microphone recording
                    Log.i(TAG, "VOICE: Recording started")
                    val started = voiceRecorder.startRecording()
                    if (!started) {
                        Log.e(TAG, "VOICE: Recording failed to start")
                        _activationState.value = VoiceActivationState.ERROR
                    }
                }
            }
            return true
        } else {
            // Only one key pressed so far - wait for pair within tolerance
            _activationState.value = VoiceActivationState.WAITING_FOR_PAIR

            singleKeyTimeoutJob?.cancel()
            singleKeyTimeoutJob = coroutineScope.launch {
                delay(CHORD_TOLERANCE_MS)
                if (!isVolUpPressed || !isVolDownPressed) {
                    if (_activationState.value == VoiceActivationState.WAITING_FOR_PAIR) {
                        _activationState.value = VoiceActivationState.IDLE
                    }
                }
            }
            return true
        }
    }

    /**
     * Intercept key up events. Returns true if the event was handled/consumed.
     */
    fun handleKeyUp(keyCode: Int): Boolean {
        if (keyCode != KeyEvent.KEYCODE_VOLUME_UP && keyCode != KeyEvent.KEYCODE_VOLUME_DOWN) {
            return false
        }

        when (keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP -> isVolUpPressed = false
            KeyEvent.KEYCODE_VOLUME_DOWN -> isVolDownPressed = false
        }

        holdTimerJob?.cancel()
        holdTimerJob = null

        singleKeyTimeoutJob?.cancel()
        singleKeyTimeoutJob = null

        val currentState = _activationState.value

        if (currentState == VoiceActivationState.RECORDING) {
            _activationState.value = VoiceActivationState.STOPPING
            Log.i(TAG, "VOICE: Recording stopped")

            // Stop recording and finalize audio file
            voiceRecorder.stopRecordingAndSend { result ->
                val file = voiceRecorder.getAudioFile()
                if (file != null && file.exists()) {
                    Log.i(TAG, "VOICE: Audio file created: ${file.name}")
                }
                _activationState.value = VoiceActivationState.READY_TO_UPLOAD
            }
            return true
        } else if (currentState == VoiceActivationState.ARMED || currentState == VoiceActivationState.WAITING_FOR_PAIR) {
            // Released before 1-second threshold -> cancel cleanly
            _activationState.value = VoiceActivationState.IDLE
            return true
        }

        if (!isVolUpPressed && !isVolDownPressed) {
            _activationState.value = VoiceActivationState.IDLE
        }

        return true
    }

    fun reset() {
        holdTimerJob?.cancel()
        holdTimerJob = null
        singleKeyTimeoutJob?.cancel()
        singleKeyTimeoutJob = null
        isVolUpPressed = false
        isVolDownPressed = false
        _activationState.value = VoiceActivationState.IDLE
    }
}
