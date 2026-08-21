package com.hapticguide.navigation

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import android.util.Log
import java.io.File

/**
 * Microphone voice command audio recorder.
 * Captures short audio clips (M4A / AAC) from the device mic and exposes the recorded file for upload.
 */
open class VoiceRecorder(
    private val context: Context,
    val httpClient: NavHttpClient = NavHttpClient(),
) {
    companion object {
        private const val TAG = "VOICE"
        const val AUDIO_FILENAME = "voice_command.m4a"
    }

    private var recorder: MediaRecorder? = null
    private var audioFile: File? = null
    @Volatile var isRecording: Boolean = false
        protected set

    fun bindBackend(ip: String, httpPort: Int) {
        httpClient.serverIp = ip.trim()
        httpClient.httpPort = httpPort
    }

    fun getAudioFile(): File? = audioFile

    fun getAudioBytes(): ByteArray? {
        val file = audioFile
        return if (file != null && file.exists() && file.length() > 0) {
            file.readBytes()
        } else {
            null
        }
    }

    open fun startRecording(): Boolean {
        if (isRecording) return false

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

            isRecording = true
            Log.i(TAG, "VOICE: Recording started")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start recording: ${e.message}", e)
            isRecording = false
            return false
        }
    }

    open fun stopRecording(): File? {
        if (!isRecording) return null

        try {
            recorder?.apply {
                stop()
                release()
            }
        } catch (e: Exception) {
            Log.e(TAG, "VOICE: Failed to stop recording: ${e.message}", e)
        } finally {
            recorder = null
            isRecording = false
        }

        val file = audioFile
        val exists = file != null && file.exists()
        val size = if (exists) file!!.length() else 0L

        Log.i(TAG, "VOICE: recording stopped")
        Log.i(TAG, "VOICE: file path = ${file?.absolutePath ?: "null"}")
        Log.i(TAG, "VOICE: file exists = $exists")
        Log.i(TAG, "VOICE: file size = $size bytes")
        Log.i(TAG, "VOICE: MIME = audio/mp4")

        return if (exists && size > 0) file else null
    }

    open fun cancelRecording() {
        try {
            recorder?.apply {
                stop()
                release()
            }
        } catch (_: Exception) {}
        recorder = null
        isRecording = false
        cleanupAudioFile()
    }

    open fun cleanupAudioFile() {
        try {
            audioFile?.let { file ->
                if (file.exists()) {
                    file.delete()
                }
            }
        } catch (_: Exception) {}
    }
}
