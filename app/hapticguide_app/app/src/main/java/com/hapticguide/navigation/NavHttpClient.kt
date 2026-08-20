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

    fun postFix(latitude: Double, longitude: Double, accuracyM: Float?) {
        val body = JSONObject().apply {
            put("latitude", latitude)
            put("longitude", longitude)
            if (accuracyM != null && accuracyM >= 0f) {
                put("accuracy_m", accuracyM.toDouble())
            }
        }
        post("/nav/gps", body)
    }

    fun postFault(health: String, message: String) {
        val body = JSONObject().apply {
            put("health", health)
            put("message", message)
        }
        post("/nav/gps/fault", body)
    }

    private fun post(path: String, body: JSONObject) {
        val ip = serverIp.trim()
        if (ip.isEmpty() || httpPort <= 0) return

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
            conn.inputStream.use { it.readBytes() }
        } catch (e: Exception) {
            Log.w(TAG, "POST $path failed: ${e.message}")
            runCatching { conn?.errorStream?.close() }
        } finally {
            conn?.disconnect()
        }
    }
}
