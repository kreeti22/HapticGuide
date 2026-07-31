package com.hapticguide.camera

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * FrameUploader is responsible for sending compressed JPEG frames to the backend server.
 * It uses OkHttp and guarantees that only one upload is active at a time to prioritize lowest latency.
 */
class FrameUploader(private val scope: CoroutineScope) {

    // OkHttpClient with short timeouts for fast failover/reconnection
    private val client = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .writeTimeout(2, TimeUnit.SECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .build()

    // Atomic flag ensuring only one upload request is active at any time
    val isUploading = AtomicBoolean(false)

    /**
     * Callback interface to communicate upload status to the UI/caller
     */
    interface UploadCallback {
        fun onUploadSuccess()
        fun onUploadFailure(error: String)
    }

    /**
     * Uploads a compressed JPEG byte array asynchronously.
     * If a previous upload is still active, this method returns false immediately
     * and the frame is dropped (no queuing).
     *
     * @param serverIp The target server IP address (e.g. "192.168.1.10")
     * @param jpegData The JPEG compressed byte array of the frame
     * @param callback Callbacks to notify success or failure
     * @return True if the upload task was successfully queued/started, false if dropped.
     */
    fun uploadFrame(
        serverAddress: String,
        jpegData: ByteArray,
        callback: UploadCallback
    ): Boolean {
        // Atomically check if an upload is active, and set it to true.
        // If it was already true, we return false and drop the frame (Requirement 7).
        if (!isUploading.compareAndSet(false, true)) {
            return false
        }

        // Launch the network operation in a background thread using Coroutines (Requirement 5 & 15)
        scope.launch(Dispatchers.IO) {
            try {
                val mediaType = "image/jpeg".toMediaType()
                val requestBody = MultipartBody.Builder()
                    .setType(MultipartBody.FORM)
                    .addFormDataPart("image", "frame.jpg", jpegData.toRequestBody(mediaType))
                    .build()

                // Construct full URL robustly (Requirement 4 & User customization request)
                val cleanAddress = serverAddress.trim()
                val url = if (cleanAddress.startsWith("http://") || cleanAddress.startsWith("https://")) {
                    cleanAddress
                } else {
                    "http://$cleanAddress"
                }

                val request = Request.Builder()
                    .url(url)
                    .post(requestBody)
                    .build()

                Log.d("FrameUploader", "Uploading frame to target: $url")

                // Execute the request synchronously in this background coroutine
                client.newCall(request).execute().use { response ->
                    if (response.isSuccessful) {
                        Log.d("FrameUploader", "Frame uploaded successfully to $url")
                        // Success - Server returned HTTP 200 (Requirement 9)
                        callback.onUploadSuccess()
                    } else {
                        Log.e("FrameUploader", "Upload failed with HTTP code: ${response.code} (url: $url)")
                        callback.onUploadFailure("HTTP ${response.code}")
                    }
                }
            } catch (e: IOException) {
                Log.e("FrameUploader", "Network I/O exception during frame upload: ${e.message}")
                callback.onUploadFailure(e.message ?: "Network error")
            } catch (e: Exception) {
                Log.e("FrameUploader", "Unexpected error during frame upload: ${e.message}")
                callback.onUploadFailure(e.message ?: "Unexpected error")
            } finally {
                // Reset the upload flag to allow subsequent frames to upload
                isUploading.set(false)
            }
        }
        return true
    }
}
