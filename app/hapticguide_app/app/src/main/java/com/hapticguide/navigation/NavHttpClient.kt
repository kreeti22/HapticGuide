package com.hapticguide.navigation

import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Posts GPS samples to the existing FastAPI server.
 * Uses HTTP on the backend port (default 8000), not the camera TCP port.
 */
class NavHttpClient {

    companion object {
        private const val TAG = "NavHttpClient"
        private const val TIMEOUT_MS = 2000
    }

    @Volatile var serverIp: String = ""
    @Volatile var httpPort: Int = 8000

    fun postFix(latitude: Double, longitude: Double, accuracyM: Float?): JSONObject? {
        val body = JSONObject().apply {
            put("latitude", latitude)
            put("longitude", longitude)
            if (accuracyM != null && accuracyM >= 0f) {
                put("accuracy_m", accuracyM.toDouble())
            }
        }
        return post("/nav/gps", body)
    }

    fun postFault(health: String, message: String): JSONObject? {
        val body = JSONObject().apply {
            put("health", health)
            put("message", message)
        }
        return post("/nav/gps/fault", body)
    }

    fun postVoice(audioBytes: ByteArray, filename: String = "voice_command.m4a"): JSONObject? {
        val ip = serverIp.trim()
        if (ip.isEmpty() || httpPort <= 0) return null

        val url = URL("http://$ip:$httpPort/nav/voice")
        var conn: HttpURLConnection? = null
        try {
            conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 10000
                readTimeout = 10000
                doOutput = true
                setRequestProperty("Content-Type", "audio/mp4")
            }
            conn.outputStream.use { os ->
                os.write(audioBytes)
            }
            val responseCode = conn.responseCode
            val responseBytes = if (responseCode in 200..299) {
                conn.inputStream.use { it.readBytes() }
            } else {
                conn.errorStream?.use { it.readBytes() }
            }
            if (responseBytes != null && responseBytes.isNotEmpty()) {
                return JSONObject(String(responseBytes, Charsets.UTF_8))
            }
        } catch (e: Exception) {
            Log.w(TAG, "POST /nav/voice failed: ${e.message}")
        } finally {
            conn?.disconnect()
        }
        return null
    }

    fun getProgress(): JSONObject? = get("/nav/progress")

    fun getStatus(): JSONObject? = get("/nav/status")

    private fun get(path: String): JSONObject? {
        val ip = serverIp.trim()
        if (ip.isEmpty() || httpPort <= 0) return null

        val url = URL("http://$ip:$httpPort$path")
        var conn: HttpURLConnection? = null
        try {
            conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = TIMEOUT_MS
                readTimeout = TIMEOUT_MS
                setRequestProperty("Accept", "application/json")
            }
            val responseCode = conn.responseCode
            val responseBytes = if (responseCode in 200..299) {
                conn.inputStream.use { it.readBytes() }
            } else {
                conn.errorStream?.use { it.readBytes() }
            }
            if (responseBytes != null && responseBytes.isNotEmpty()) {
                return JSONObject(String(responseBytes, Charsets.UTF_8))
            }
        } catch (e: Exception) {
            Log.w(TAG, "GET $path failed: ${e.message}")
        } finally {
            conn?.disconnect()
        }
        return null
    }

    private fun post(path: String, body: JSONObject): JSONObject? {
        val ip = serverIp.trim()
        if (ip.isEmpty() || httpPort <= 0) return null

        val url = URL("http://$ip:$httpPort$path")
        var conn: HttpURLConnection? = null
        try {
            conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = TIMEOUT_MS
                readTimeout = TIMEOUT_MS
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
            conn.outputStream.use { os ->
                os.write(body.toString().toByteArray(Charsets.UTF_8))
            }
            val responseCode = conn.responseCode
            val responseBytes = if (responseCode in 200..299) {
                conn.inputStream.use { it.readBytes() }
            } else {
                conn.errorStream?.use { it.readBytes() }
            }
            if (responseBytes != null && responseBytes.isNotEmpty()) {
                return JSONObject(String(responseBytes, Charsets.UTF_8))
            }
        } catch (e: Exception) {
            Log.w(TAG, "POST $path failed: ${e.message}")
        } finally {
            conn?.disconnect()
        }
        return null
    }
}
