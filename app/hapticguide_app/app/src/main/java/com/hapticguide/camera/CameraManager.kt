package com.hapticguide.camera

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.util.Log
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

/**
 * CameraManager
 * -------------
 * Binds CameraX and forwards every frame to TcpFrameSender.
 *
 * Pipeline
 * --------
 *   CameraX (YUV_420_888)
 *        │
 *        ├──► PreviewView  (live viewfinder — always active)
 *        └──► ImageAnalysis
 *                  │
 *                  ▼ yuv420ToNv21()        — in-place, preallocated buffer
 *                  ▼ YuvImage.compressToJpeg() — quality 70
 *                  ▼ TcpFrameSender.sendFrame()
 *
 * Frame drop policy
 * -----------------
 * ImageAnalysis is configured with STRATEGY_KEEP_ONLY_LATEST.
 * If TcpFrameSender is busy or disconnected, the frame is dropped silently.
 * Latency beats coverage.
 *
 * Camera FPS tracking
 * -------------------
 * Counted in the ImageAnalysis callback and exposed as cameraFps StateFlow.
 * Updated every second.
 */
class CameraManager(
    private val context:     Context,
    private val tcpSender:   TcpFrameSender,
    private val jpegQuality: Int = 70,
) {
    companion object {
        private const val TAG = "CameraManager"
        private val CAPTURE_SIZE = Size(640, 480)
    }

    private val mainExecutor   = ContextCompat.getMainExecutor(context)
    private val cameraExecutor = Executors.newSingleThreadExecutor()

    // Camera FPS — published to UI
    private val _cameraFps = MutableStateFlow(0f)
    val cameraFps: StateFlow<Float> = _cameraFps.asStateFlow()

    private var fpsCameraCount  = 0
    private var fpsCameraLastMs = 0L

    // Preallocated NV21 buffer (640×480 × 1.5 = 460 800 bytes)
    private var nv21Buffer    = ByteArray(CAPTURE_SIZE.width * CAPTURE_SIZE.height * 3 / 2)
    private val jpegStream    = ByteArrayOutputStream(64_000)

    private var isCameraReady = false
    var isStreaming           = false
        private set

    // -------------------------------------------------------------------------
    // Camera lifecycle
    // -------------------------------------------------------------------------

    fun startCamera(lifecycleOwner: LifecycleOwner, previewView: PreviewView) {
        if (isCameraReady) return

        val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
        cameraProviderFuture.addListener({
            try {
                val cameraProvider = cameraProviderFuture.get()

                val resolutionSelector = ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(
                            CAPTURE_SIZE,
                            ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER,
                        )
                    )
                    .build()

                // ── Preview — live viewfinder ────────────────────────────────
                val preview = Preview.Builder()
                    .setResolutionSelector(resolutionSelector)
                    .build()
                    .also { it.surfaceProvider = previewView.surfaceProvider }

                // ── ImageAnalysis — frame capture ────────────────────────────
                val analysis = ImageAnalysis.Builder()
                    .setResolutionSelector(resolutionSelector)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                    .build()

                analysis.setAnalyzer(cameraExecutor) { imageProxy ->
                    processFrame(imageProxy)
                }

                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis,
                )

                isCameraReady = true
                Log.i(TAG, "Camera bound — ${CAPTURE_SIZE.width}×${CAPTURE_SIZE.height}")

            } catch (e: Exception) {
                Log.e(TAG, "Failed to bind camera: ${e.message}", e)
            }
        }, mainExecutor)
    }

    // -------------------------------------------------------------------------
    // Streaming control
    // -------------------------------------------------------------------------

    fun startStreaming(ip: String, port: Int) {
        if (!isCameraReady) { Log.w(TAG, "Camera not ready"); return }
        tcpSender.start(ip, port)
        isStreaming = true
        Log.i(TAG, "Streaming started → $ip:$port")
    }

    fun stopStreaming() {
        tcpSender.stop()
        isStreaming = false
        Log.i(TAG, "Streaming stopped")
    }

    // -------------------------------------------------------------------------
    // Per-frame processing  (runs on cameraExecutor — single background thread)
    // -------------------------------------------------------------------------

    private fun processFrame(imageProxy: ImageProxy) {
        try {
            trackCameraFps()

            // Drop immediately when not streaming to keep the encoder idle.
            if (!isStreaming) return

            val width  = imageProxy.width
            val height = imageProxy.height

            // Resize NV21 buffer if the actual resolution differs from expected.
            val required = width * height * 3 / 2
            if (nv21Buffer.size != required) {
                nv21Buffer = ByteArray(required)
            }

            // ── YUV_420_888 → NV21 (in-place, no allocation) ────────────────
            yuv420ToNv21(imageProxy, nv21Buffer)

            // ── NV21 → JPEG (quality 70) ─────────────────────────────────────
            jpegStream.reset()
            YuvImage(nv21Buffer, ImageFormat.NV21, width, height, null)
                .compressToJpeg(Rect(0, 0, width, height), jpegQuality, jpegStream)
            val jpeg = jpegStream.toByteArray()

            // ── Send over TCP ─────────────────────────────────────────────────
            tcpSender.sendFrame(jpeg)

        } finally {
            // Always close — returns the CameraX buffer to the sensor pipeline.
            imageProxy.close()
        }
    }

    // -------------------------------------------------------------------------
    // YUV_420_888 → NV21 conversion
    // -------------------------------------------------------------------------

    /**
     * Convert an ImageProxy (YUV_420_888) to NV21 in-place into [output].
     *
     * NV21 layout: Y plane (width × height bytes), then interleaved VU
     * (width/2 × height/2 × 2 bytes).
     *
     * Handles non-unit pixel strides and non-width row strides correctly.
     * These are common on Snapdragon and MediaTek devices.
     */
    private fun yuv420ToNv21(image: ImageProxy, output: ByteArray) {
        val width  = image.width
        val height = image.height

        val yPlane = image.planes[0]
        val uPlane = image.planes[1]
        val vPlane = image.planes[2]

        val yBuf = yPlane.buffer
        val uBuf = uPlane.buffer
        val vBuf = vPlane.buffer

        val yRowStride    = yPlane.rowStride
        val yPixelStride  = yPlane.pixelStride
        val uvRowStride   = uPlane.rowStride   // same for U and V on all known Android devices
        val uvPixelStride = uPlane.pixelStride // same for U and V

        var pos = 0

        // ── Y plane ──────────────────────────────────────────────────────────
        for (row in 0 until height) {
            val rowBase = row * yRowStride
            for (col in 0 until width) {
                output[pos++] = yBuf.get(rowBase + col * yPixelStride)
            }
        }

        // ── VU interleaved (NV21 has V before U) ─────────────────────────────
        val uvWidth  = width  / 2
        val uvHeight = height / 2

        for (row in 0 until uvHeight) {
            val uRowBase = row * uvRowStride
            val vRowBase = row * vPlane.rowStride   // use vPlane.rowStride — may differ
            for (col in 0 until uvWidth) {
                output[pos++] = vBuf.get(vRowBase + col * uvPixelStride)  // V first
                output[pos++] = uBuf.get(uRowBase + col * uvPixelStride)  // then U
            }
        }
    }

    // -------------------------------------------------------------------------
    // Camera FPS tracking
    // -------------------------------------------------------------------------

    private fun trackCameraFps() {
        val now = System.currentTimeMillis()
        fpsCameraCount++
        if (fpsCameraLastMs == 0L) { fpsCameraLastMs = now; return }
        val elapsed = now - fpsCameraLastMs
        if (elapsed >= 1_000L) {
            _cameraFps.value  = fpsCameraCount * 1_000f / elapsed
            fpsCameraCount    = 0
            fpsCameraLastMs   = now
        }
    }

    // -------------------------------------------------------------------------
    // Lifecycle
    // -------------------------------------------------------------------------

    fun shutdown() {
        stopStreaming()
        cameraExecutor.shutdownNow()
    }
}
