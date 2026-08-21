package com.hapticguide.navigation

import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

/**
 * Manages physical dual-button (Volume Up + Volume Down) chord detection for voice input
 * and coordinates the full recording, automatic upload, and navigation state machine.
 *
 * Authoritative lifecycle:
 * IDLE
 *  ↓ (both volume buttons detected)
 * ARMED (1-second hold timer)
 *  ↓ (1-second hold satisfied + haptic pulse)
 * RECORDING (captures microphone audio while buttons are held)
 *  ↓ (button release)
 * STOPPING (finalizes audio file)
 *  ↓
 * UPLOAD_PENDING
 *  ↓
 * UPLOADING (posts audio to /nav/voice)
 *  ↓
 * SERVER_RESPONSE (processes transcription and route calculation)
 *  ↓
 * NAVIGATION (route ready / started) or ERROR
 */
class VolumeKeyVoiceTrigger(
    private val voiceRecorder: VoiceRecorder,
    private val phoneHapticPlayer: PhoneHapticPlayer,
    private val coroutineScope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Main),
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val onNavigationResult: ((JSONObject?) -> Unit)? = null,
) {

    companion object {
        private const val TAG = "VOICE"
        const val HOLD_THRESHOLD_MS: Long = 1000L
        const val CHORD_TOLERANCE_MS: Long = 400L
    }

    private val _activationState = MutableStateFlow(VoiceActivationState.IDLE)
    val activationState: StateFlow<VoiceActivationState> = _activationState.asStateFlow()

    private val _statusDetail = MutableStateFlow("")
    val statusDetail: StateFlow<String> = _statusDetail.asStateFlow()

    private val _lastDestination = MutableStateFlow<String?>(null)
    val lastDestination: StateFlow<String?> = _lastDestination.asStateFlow()

    private val _lastTranscript = MutableStateFlow<String?>(null)
    val lastTranscript: StateFlow<String?> = _lastTranscript.asStateFlow()

    @Volatile var isVolUpPressed: Boolean = false
        private set
    @Volatile var isVolDownPressed: Boolean = false
        private set

    private var holdTimerJob: Job? = null
    private var singleKeyTimeoutJob: Job? = null
    private var uploadJob: Job? = null

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

        when (keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP -> {
                Log.i(TAG, "VOICE: Volume Up detected")
                isVolUpPressed = true
            }
            KeyEvent.KEYCODE_VOLUME_DOWN -> {
                Log.i(TAG, "VOICE: Volume Down detected")
                isVolDownPressed = true
            }
        }

        // Check if BOTH keys are now pressed
        if (isVolUpPressed && isVolDownPressed) {
            singleKeyTimeoutJob?.cancel()
            singleKeyTimeoutJob = null

            Log.i(TAG, "VOICE: Both buttons held")
            _activationState.value = VoiceActivationState.ARMED
            _statusDetail.value = "Hold both buttons (1s)..."

            // Start 1-second hold timer
            holdTimerJob?.cancel()
            holdTimerJob = coroutineScope.launch {
                delay(HOLD_THRESHOLD_MS)

                // Verify both keys are still held after 1s
                if (isVolUpPressed && isVolDownPressed) {
                    _activationState.value = VoiceActivationState.RECORDING
                    _statusDetail.value = "Recording... Speak now"

                    // 1. Short phone haptic confirmation
                    phoneHapticPlayer.playPattern(longArrayOf(0, 80))

                    // 2. Start microphone recording
                    Log.i(TAG, "VOICE: Recording started")
                    val started = voiceRecorder.startRecording()
                    if (!started) {
                        Log.e(TAG, "VOICE: Recording failed to start")
                        _activationState.value = VoiceActivationState.ERROR
                        _statusDetail.value = "Failed to start microphone recording"
                    }
                }
            }
            return true
        } else {
            // Only one key pressed so far - wait for pair within tolerance
            _activationState.value = VoiceActivationState.WAITING_FOR_PAIR
            _statusDetail.value = "Waiting for second button..."

            singleKeyTimeoutJob?.cancel()
            singleKeyTimeoutJob = coroutineScope.launch {
                delay(CHORD_TOLERANCE_MS)
                if (!isVolUpPressed || !isVolDownPressed) {
                    if (_activationState.value == VoiceActivationState.WAITING_FOR_PAIR) {
                        _activationState.value = VoiceActivationState.IDLE
                        _statusDetail.value = ""
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
            stopRecordingAndUpload()
            return true
        } else if (currentState == VoiceActivationState.ARMED || currentState == VoiceActivationState.WAITING_FOR_PAIR) {
            // Released before 1-second threshold -> cancel cleanly
            _activationState.value = VoiceActivationState.IDLE
            _statusDetail.value = ""
            return true
        }

        if (!isVolUpPressed && !isVolDownPressed && !_activationState.value.isProcessingState) {
            _activationState.value = VoiceActivationState.IDLE
            _statusDetail.value = ""
        }

        return true
    }

    /**
     * Start recording manually (e.g. from on-screen Voice Destination button).
     */
    fun startManualRecording(): Boolean {
        holdTimerJob?.cancel()
        singleKeyTimeoutJob?.cancel()
        uploadJob?.cancel()

        _activationState.value = VoiceActivationState.RECORDING
        _statusDetail.value = "Recording... Speak now"
        phoneHapticPlayer.playPattern(longArrayOf(0, 80))
        Log.i(TAG, "VOICE: Manual recording started")
        val started = voiceRecorder.startRecording()
        if (!started) {
            Log.e(TAG, "VOICE: Manual recording failed to start")
            _activationState.value = VoiceActivationState.ERROR
            _statusDetail.value = "Failed to start microphone recording"
            return false
        }
        return true
    }

    /**
     * Stop recording and initiate automatic upload to /nav/voice.
     */
    fun stopRecordingAndUpload() {
        holdTimerJob?.cancel()
        singleKeyTimeoutJob?.cancel()

        _activationState.value = VoiceActivationState.STOPPING
        _statusDetail.value = "Finalizing audio..."
        Log.i(TAG, "VOICE: Recording stopped")

        val file = voiceRecorder.stopRecording()
        if (file != null && file.exists() && file.length() > 0) {
            Log.i(TAG, "VOICE: Audio file created: ${file.name} (${file.length()} bytes)")
            startAutomaticUpload(file)
        } else {
            Log.w(TAG, "VOICE: No audio recorded or file empty")
            _activationState.value = VoiceActivationState.ERROR
            _statusDetail.value = "No audio recorded"
        }
    }

    /**
     * Toggle recording state: if recording, stops and uploads; otherwise starts recording.
     */
    fun toggleRecording() {
        val current = _activationState.value
        if (current == VoiceActivationState.RECORDING) {
            stopRecordingAndUpload()
        } else {
            startManualRecording()
        }
    }

    fun startAutomaticUpload(file: File) {
        uploadJob?.cancel()
        uploadJob = coroutineScope.launch {
            _activationState.value = VoiceActivationState.UPLOAD_PENDING
            _statusDetail.value = "Upload pending..."

            _activationState.value = VoiceActivationState.UPLOADING
            _statusDetail.value = "Uploading audio..."

            val bytes = withContext(ioDispatcher) {
                try {
                    file.readBytes()
                } catch (e: Exception) {
                    null
                }
            }

            if (bytes == null || bytes.isEmpty()) {
                _activationState.value = VoiceActivationState.ERROR
                _statusDetail.value = "Failed to read audio file"
                return@launch
            }

            _activationState.value = VoiceActivationState.SERVER_RESPONSE
            _statusDetail.value = "Processing with Groq..."

            val response = withContext(ioDispatcher) {
                voiceRecorder.httpClient.postVoice(bytes, file.name)
            }

            if (response != null) {
                val ok = response.optBoolean("ok", false)
                val transcript = response.optString("transcript", "")
                val dest = response.optJSONObject("destination")?.optString("name", "")
                val error = response.optString("error", "")

                if (!transcript.isNullOrEmpty()) {
                    _lastTranscript.value = transcript
                    Log.i(TAG, "VOICE COMMAND RECEIVED")
                    Log.i(TAG, "TRANSCRIPT: $transcript")
                }

                if (ok) {
                    _lastDestination.value = dest
                    _activationState.value = VoiceActivationState.NAVIGATION
                    _statusDetail.value = if (!dest.isNullOrEmpty()) "Destination: $dest" else "Navigation started"
                    onNavigationResult?.invoke(response)
                } else {
                    _activationState.value = VoiceActivationState.ERROR
                    _statusDetail.value = if (error.isNotEmpty()) error else "Voice processing failed"
                    onNavigationResult?.invoke(response)
                }
            } else {
                _activationState.value = VoiceActivationState.ERROR
                val targetIp = voiceRecorder.httpClient.serverIp
                val targetPort = voiceRecorder.httpClient.httpPort
                _statusDetail.value = if (targetIp.isEmpty()) {
                    "Server IP not set"
                } else {
                    "Cannot reach server ($targetIp:$targetPort)"
                }
                onNavigationResult?.invoke(null)
            }
            voiceRecorder.cleanupAudioFile()
        }
    }

    fun reset() {
        holdTimerJob?.cancel()
        holdTimerJob = null
        singleKeyTimeoutJob?.cancel()
        singleKeyTimeoutJob = null
        uploadJob?.cancel()
        uploadJob = null
        isVolUpPressed = false
        isVolDownPressed = false
        voiceRecorder.cancelRecording()
        _activationState.value = VoiceActivationState.IDLE
        _statusDetail.value = ""
    }
}
