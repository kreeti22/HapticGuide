package com.hapticguide.navigation

import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Posts GPS samples to the existing FastAPI server.
 * Uses HTTP on the backend port (default 8000), not the camera TCP port.
 */
open class NavHttpClient {

    companion object {
        private const val TAG = "NavHttpClient"
        private const val TIMEOUT_MS = 2000
    }

    @Volatile var serverIp: String = ""
    @Volatile var httpPort: Int = 8000

    open fun postFix(latitude: Double, longitude: Double, accuracyM: Float?): JSONObject? {
        val body = JSONObject().apply {
            put("latitude", latitude)
            put("longitude", longitude)
            if (accuracyM != null && accuracyM >= 0f) {
                put("accuracy_m", accuracyM.toDouble())
            }
        }
        return post("/nav/gps", body)
    }

    open fun postFault(health: String, message: String): JSONObject? {
        val body = JSONObject().apply {
            put("health", health)
            put("message", message)
        }
        return post("/nav/gps/fault", body)
    }

    open fun postVoice(audioBytes: ByteArray, filename: String = "voice_command.m4a"): JSONObject? {
        val ip = serverIp.trim()
        val uploadUrl = "http://$ip:$httpPort/nav/voice"
        Log.i("VOICE", "VOICE: upload URL = $uploadUrl")
        Log.i("VOICE", "VOICE: file size = ${audioBytes.size} bytes")
        Log.i("VOICE", "VOICE: MIME = audio/mp4")
        Log.i("VOICE", "VOICE: upload started")

        if (ip.isEmpty() || httpPort <= 0) {
            Log.e("VOICE", "VOICE: upload failed = server IP or port is not configured (ip='$ip', port=$httpPort)")
            return null
        }

        val boundary = "===Boundary" + System.currentTimeMillis() + "==="
        val lineEnd = "\r\n"
        val twoHyphens = "--"

        var conn: HttpURLConnection? = null
        try {
            val url = URL(uploadUrl)
            conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 15000
                readTimeout = 20000
                doOutput = true
                doInput = true
                useCaches = false
                setRequestProperty("Connection", "Keep-Alive")
                setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                setRequestProperty("Accept", "application/json")
            }

            conn.outputStream.use { os ->
                val writer = java.io.PrintWriter(java.io.OutputStreamWriter(os, Charsets.UTF_8), true)
                // Write multipart file header with field name 'file'
                writer.append(twoHyphens).append(boundary).append(lineEnd)
                writer.append("Content-Disposition: form-data; name=\"file\"; filename=\"").append(filename).append("\"").append(lineEnd)
                writer.append("Content-Type: audio/mp4").append(lineEnd)
                writer.append(lineEnd).flush()

                // Write actual audio bytes
                os.write(audioBytes)
                os.flush()

                writer.append(lineEnd).flush()
                writer.append(twoHyphens).append(boundary).append(twoHyphens).append(lineEnd).flush()
            }

            val responseCode = conn.responseCode
            Log.i("VOICE", "VOICE: HTTP status = $responseCode")

            val responseBytes = if (responseCode in 200..299) {
                conn.inputStream.use { it.readBytes() }
            } else {
                conn.errorStream?.use { it.readBytes() }
            }

            val responseStr = if (responseBytes != null && responseBytes.isNotEmpty()) {
                String(responseBytes, Charsets.UTF_8)
            } else {
                ""
            }
            Log.i("VOICE", "VOICE: response = $responseStr")

            if (responseStr.isNotEmpty()) {
                return JSONObject(responseStr)
            } else {
                Log.w("VOICE", "VOICE: upload failed = empty server response (HTTP $responseCode)")
            }
        } catch (e: Exception) {
            Log.e("VOICE", "VOICE: upload failed = ${e.message}", e)
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
