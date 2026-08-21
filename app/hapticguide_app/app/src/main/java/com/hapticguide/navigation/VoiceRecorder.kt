package com.hapticguide.navigation

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File

/**
 * Microphone voice command recorder for navigation destination input.
 * Captures short audio clips and sends them to FastAPI /nav/voice.
 */
class VoiceRecorder(
    private val context: Context,
    private val httpClient: NavHttpClient = NavHttpClient(),
) {
    companion object {
        private const val TAG = "VoiceRecorder"
        private const val AUDIO_FILENAME = "voice_command.m4a"
    }

    data class VoiceState(
        val isRecording: Boolean = false,
        val isProcessing: Boolean = false,
        val statusMessage: String = "Idle",
        val lastTranscript: String? = null,
        val lastDestination: String? = null,
    )

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _state = MutableStateFlow(VoiceState())
    val state: StateFlow<VoiceState> = _state.asStateFlow()

    private var recorder: MediaRecorder? = null
    private var audioFile: File? = null

    fun bindBackend(ip: String, httpPort: Int) {
        httpClient.serverIp = ip.trim()
        httpClient.httpPort = httpPort
    }

    fun startRecording(): Boolean {
        if (_state.value.isRecording) return false

        try {
            val file = File(context.cacheDir, AUDIO_FILENAME)
            if (file.exists()) file.delete()
            audioFile = file

            recorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                MediaRecorder(context)
            } else {
                @Suppress("DEPRECATION")
                MediaRecorder()
            }.apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setOutputFile(file.absolutePath)
                prepare()
                start()
            }

            _state.value = _state.value.copy(
                isRecording = true,
                statusMessage = "Listening...",
            )
            Log.i(TAG, "Voice recording started")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start recording: ${e.message}", e)
            _state.value = _state.value.copy(
                isRecording = false,
                statusMessage = "Recording error: ${e.message}",
            )
            return false
        }
    }

    fun stopRecordingAndSend(onResult: ((JSONObject?) -> Unit)? = null) {
        if (!_state.value.isRecording) return

        try {
            recorder?.apply {
                stop()
                release()
            }
            recorder = null
            _state.value = _state.value.copy(
                isRecording = false,
                isProcessing = true,
                statusMessage = "Transcribing with Groq...",
            )
            Log.i(TAG, "Voice recording stopped. Sending audio...")

            val file = audioFile
            if (file != null && file.exists() && file.length() > 0) {
                scope.launch {
                    val bytes = file.readBytes()
                    val result = httpClient.postVoice(bytes, file.name)
                    val ok = result?.optBoolean("ok", false) == true
                    val transcript = result?.optString("transcript", "")
                    val dest = result?.optJSONObject("destination")?.optString("name", "")

                    _state.value = _state.value.copy(
                        isProcessing = false,
                        statusMessage = if (ok) "Destination: $dest" else (result?.optString("error", "Error") ?: "Error"),
                        lastTranscript = transcript,
                        lastDestination = dest,
                    )
                    onResult?.invoke(result)
                }
            } else {
                _state.value = _state.value.copy(
                    isProcessing = false,
                    statusMessage = "No audio recorded",
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to stop/send recording: ${e.message}", e)
            _state.value = _state.value.copy(
                isRecording = false,
                isProcessing = false,
                statusMessage = "Error: ${e.message}",
            )
        }
    }

    fun cancelRecording() {
        try {
            recorder?.apply {
                stop()
                release()
            }
        } catch (_: Exception) {}
        recorder = null
        _state.value = _state.value.copy(
            isRecording = false,
            isProcessing = false,
            statusMessage = "Cancelled",
        )
    }
}
