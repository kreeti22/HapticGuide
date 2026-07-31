package com.hapticguide.camera

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.util.Log
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.io.ByteArrayOutputStream
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * CameraManager configures CameraX Preview and ImageAnalysis use cases.
 * It handles frame extraction, throttling, conversion to JPEG, and invokes
 * the uploader.
 */
class CameraManager(
    private val context: Context,
    private val frameUploader: FrameUploader,
    private val settingsManager: SettingsManager,
    private val onMetricsUpdated: (Int, Float) -> Unit, // (framesSent, currentFps)
    private val onConnectionStatusUpdated: (String) -> Unit
) {

    private val cameraExecutor: ExecutorService = Executors.newSingleThreadExecutor()

    // Throttling control (8 FPS = 125ms interval)
    private var lastUploadTimeMs = 0L
    private val minIntervalMs = 125L

    // Metrics tracking
    private var totalFramesSent = 0
    private var fpsCounter = 0
    private var fpsLastTimeMs = 0L
    private var currentFps = 0.0f

    // Preallocated buffer for NV21 frame data (640 * 480 * 1.5 = 460800 bytes)
    // Reusing this buffer prevents heavy garbage collection overhead (Requirement 16)
    private val expectedWidth = 640
    private val expectedHeight = 480
    private var nv21Buffer = ByteArray(expectedWidth * expectedHeight * 3 / 2)

    // Reusable stream for JPEG compression
    private val jpegOutputStream = ByteArrayOutputStream(64000) // Initial size 64KB

    fun startCamera(lifecycleOwner: LifecycleOwner, previewView: PreviewView) {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(context)

        cameraProviderFuture.addListener({
            try {
                val cameraProvider = cameraProviderFuture.get()

                // Preview Use Case
                val preview = Preview.Builder().build().also {
                    it.surfaceProvider = previewView.surfaceProvider
                }

                // ImageAnalysis Use Case (640x480)
                // Use the modern API (or setTargetResolution) to lock in 640x480.
                @Suppress("DEPRECATION")
                val imageAnalysis = ImageAnalysis.Builder()
                    .setTargetResolution(Size(expectedWidth, expectedHeight))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()

                imageAnalysis.setAnalyzer(cameraExecutor) { imageProxy ->
                    processImageFrame(imageProxy)
                }

                // Default back camera selection
                val cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA

                // Unbind previous use cases before rebinding
                cameraProvider.unbindAll()

                // Bind use cases to Lifecycle
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    cameraSelector,
                    preview,
                    imageAnalysis
                )

                onConnectionStatusUpdated("Camera Ready")

            } catch (e: Exception) {
                Log.e("CameraManager", "Failed to bind camera use cases", e)
                onConnectionStatusUpdated("Camera Init Error")
            }
        }, ContextCompat.getMainExecutor(context))
    }

    /**
     * Process each incoming camera frame. This runs on a single background thread executor.
     */
    private fun processImageFrame(imageProxy: ImageProxy) {
        val now = System.currentTimeMillis()

        // 1. Enforce max 8 FPS limit (Requirement 6)
        if (now - lastUploadTimeMs < minIntervalMs) {
            imageProxy.close()
            return
        }

        // 2. Keep only one upload active. If busy, drop frame (Requirement 7)
        if (frameUploader.isUploading.get()) {
            imageProxy.close()
            return
        }

        val width = imageProxy.width
        val height = imageProxy.height
        val requiredSize = width * height * 3 / 2

        // Verify and dynamically scale the buffer if dimensions change (e.g. portrait rotation)
        var buffer = nv21Buffer
        if (buffer.size != requiredSize) {
            Log.d("CameraManager", "Adjusting NV21 buffer size to $requiredSize (resolution: ${width}x${height})")
            buffer = ByteArray(requiredSize)
            nv21Buffer = buffer
        }

        try {
            // 3. Convert YUV_420_888 to NV21 into the preallocated buffer (Requirement 16)
            yuv420ToNv21(imageProxy, buffer)

            // 4. Single-pass: NV21 → decoded Bitmap via YuvImage, scale to 416×416, compress to JPEG.
            //    This replaces the previous double encode/decode cycle (NV21→JPEG→Bitmap→JPEG),
            //    saving one full JPEG encode and one JPEG decode per frame for higher FPS.
            val yuvImage = YuvImage(buffer, ImageFormat.NV21, width, height, null)
            jpegOutputStream.reset()
            yuvImage.compressToJpeg(Rect(0, 0, width, height), 85, jpegOutputStream)

            val options = android.graphics.BitmapFactory.Options().apply { inMutable = true }
            val originalBitmap = android.graphics.BitmapFactory.decodeByteArray(
                jpegOutputStream.toByteArray(), 0, jpegOutputStream.size(), options
            )

            // Scale to 416×416 with filter=false (nearest-neighbour) — faster and sufficient for inference
            val scaledBitmap = Bitmap.createScaledBitmap(originalBitmap, 416, 416, false)

            jpegOutputStream.reset()
            scaledBitmap.compress(Bitmap.CompressFormat.JPEG, 70, jpegOutputStream)
            val jpegBytes = jpegOutputStream.toByteArray()

            // Recycle native Bitmaps immediately to keep VM memory footprint low (Requirement 16)
            originalBitmap.recycle()
            scaledBitmap.recycle()

            // 5. CRITICAL: Close the ImageProxy IMMEDIATELY after JPEG compression.
            // This frees up the camera sensor frame buffer so that CameraX doesn't stall.
            // Do not wait for the upload network request to finish (Requirement 5).
            imageProxy.close()

            // Update timestamp of upload attempt
            lastUploadTimeMs = now

            // 6. Upload JPEG bytes asynchronously
            val serverAddress = settingsManager.getServerIp()
            onConnectionStatusUpdated("Streaming...")

            val started = frameUploader.uploadFrame(
                serverAddress,
                jpegBytes,
                object : FrameUploader.UploadCallback {
                    override fun onUploadSuccess() {
                        totalFramesSent++
                        trackFps()
                        onMetricsUpdated(totalFramesSent, currentFps)
                        onConnectionStatusUpdated("Connected")
                    }

                    override fun onUploadFailure(error: String) {
                        onConnectionStatusUpdated("Error: $error")
                    }
                }
            )

            if (!started) {
                // Should not happen as we checked frameUploader.isUploading above,
                // but if it failed to start, restore status.
                onConnectionStatusUpdated("Frame Dropped")
            }

        } catch (e: Exception) {
            Log.e("CameraManager", "Error processing frame: ${e.message}", e)
            imageProxy.close()
        }
    }

    /**
     * Converts an ImageProxy (YUV_420_888) to NV21 format and writes it directly to the target byte array.
     */
    private fun yuv420ToNv21(image: ImageProxy, target: ByteArray) {
        val width = image.width
        val height = image.height
        val yPlane = image.planes[0]
        val uPlane = image.planes[1]
        val vPlane = image.planes[2]

        val yBuffer = yPlane.buffer
        val uBuffer = uPlane.buffer
        val vBuffer = vPlane.buffer

        val ySize = yBuffer.remaining()

        // 1. Copy Y-channel
        val yRowStride = yPlane.rowStride
        val yPixelStride = yPlane.pixelStride
        var pos = 0
        
        if (yPixelStride == 1 && yRowStride == width) {
            yBuffer.get(target, 0, ySize)
            pos = ySize
        } else {
            for (row in 0 until height) {
                yBuffer.position(row * yRowStride)
                for (col in 0 until width) {
                    target[pos++] = yBuffer.get()
                    if (yPixelStride > 1) {
                        yBuffer.position(yBuffer.position() + yPixelStride - 1)
                    }
                }
            }
        }

        // 2. Interleave V and U channels (NV21 format: VUVUVU...)
        val uRowStride = uPlane.rowStride
        val uPixelStride = uPlane.pixelStride
        val vRowStride = vPlane.rowStride
        val vPixelStride = vPlane.pixelStride

        val uvWidth = width / 2
        val uvHeight = height / 2

        for (row in 0 until uvHeight) {
            val uRowStart = row * uRowStride
            val vRowStart = row * vRowStride
            for (col in 0 until uvWidth) {
                val uPos = uRowStart + col * uPixelStride
                val vPos = vRowStart + col * vPixelStride

                target[pos++] = vBuffer.get(vPos)
                target[pos++] = uBuffer.get(uPos)
            }
        }
    }

    /**
     * Live calculation of Upload FPS.
     */
    private fun trackFps() {
        val currentTime = System.currentTimeMillis()
        if (fpsLastTimeMs == 0L) {
            fpsLastTimeMs = currentTime
            fpsCounter = 1
            return
        }

        fpsCounter++
        val elapsed = currentTime - fpsLastTimeMs
        if (elapsed >= 1000) {
            currentFps = (fpsCounter * 1000f) / elapsed
            fpsCounter = 0
            fpsLastTimeMs = currentTime
        }
    }

    /**
     * Shut down executor when class is cleaned up.
     */
    fun shutdown() {
        cameraExecutor.shutdown()
    }
}
