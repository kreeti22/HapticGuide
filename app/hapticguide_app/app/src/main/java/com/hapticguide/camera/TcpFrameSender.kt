package com.hapticguide.camera

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket

/**
 * TcpFrameSender
 * --------------
 * Maintains one persistent TCP connection to the laptop receiver.
 * Sends every JPEG frame as:
 *
 *   [ 4 bytes big-endian length ][ JPEG bytes ]
 *
 * Design
 * ------
 * - One background coroutine owns the socket lifecycle.
 * - sendFrame() is called from the CameraX analysis thread.
 *   It writes directly to the socket's OutputStream under a lock.
 *   If the socket is not yet connected, the frame is silently dropped —
 *   latency is more important than coverage.
 * - On any write failure the socket is marked broken. The connection
 *   coroutine detects this and reconnects after RECONNECT_DELAY_MS.
 * - No frame queue. Latest-wins. Old frames are never sent.
 *
 * Wire format
 * -----------
 *   Byte 0-3 : image length  (big-endian uint32)
 *   Byte 4.. : JPEG bytes
 *
 * Thread safety
 * -------------
 * sendFrame() acquires socketLock before writing. The connection coroutine
 * also acquires socketLock when replacing the socket reference.
 * All state is guarded; no data race possible.
 */
class TcpFrameSender {

    companion object {
        private const val TAG               = "TcpFrameSender"
        private const val CONNECT_TIMEOUT   = 5_000          // ms
        private const val RECONNECT_DELAY   = 2_000L         // ms between reconnect attempts
        private const val SO_TIMEOUT        = 10_000         // ms socket read timeout
    }

    // ── Public state (observed by the Compose UI) ─────────────────────────────

    data class SenderState(
        val isConnected:    Boolean = false,
        val statusText:     String  = "Idle",
        val networkFps:     Float   = 0f,
        val bytesPerSecond: Long    = 0L,
        val serverIp:       String  = "",
        val serverPort:     Int     = 0,
    )

    private val _state = MutableStateFlow(SenderState())
    val state: StateFlow<SenderState> = _state.asStateFlow()

    // ── Internals ─────────────────────────────────────────────────────────────

    private val scope       = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var connectJob: Job? = null

    // Socket and stream guarded by socketLock.
    private val socketLock = Any()
    @Volatile private var socket:       Socket?       = null
    @Volatile private var outputStream: OutputStream? = null
    @Volatile private var socketBroken  = false
    @Volatile private var running       = false

    // Network metrics — updated per frame
    private var netFpsCount     = 0
    private var netFpsLastMs    = 0L
    private var bytesSentWindow = 0L
    private var bytesFpsLastMs  = 0L

    // 4-byte big-endian length header — reused every frame
    private val lengthHeader = ByteArray(4)

    // ── Config ────────────────────────────────────────────────────────────────

    @Volatile private var serverIp   = ""
    @Volatile private var serverPort = 0

    // =========================================================================
    // Public API
    // =========================================================================

    /**
     * Start the persistent connection loop targeting [ip]:[port].
     * Safe to call multiple times — previous connection is stopped first.
     */
    fun start(ip: String, port: Int) {
        stop()

        serverIp   = ip
        serverPort = port
        running    = true
        socketBroken = false

        _state.value = SenderState(
            isConnected = false,
            statusText  = "Connecting…",
            serverIp    = ip,
            serverPort  = port,
        )

        connectJob = scope.launch { connectionLoop() }
        Log.i(TAG, "TcpFrameSender started → $ip:$port")
    }

    /** Stop sending, close the socket, cancel the connection loop. */
    fun stop() {
        running = false
        connectJob?.cancel()
        connectJob = null
        closeSocket()
        _state.value = _state.value.copy(
            isConnected = false,
            statusText  = "Stopped",
            networkFps  = 0f,
            bytesPerSecond = 0L,
        )
        Log.i(TAG, "TcpFrameSender stopped")
    }

    /**
     * Send one JPEG frame over the TCP socket.
     *
     * Called from the CameraX analysis executor thread.
     * Returns immediately if not connected — frame is dropped silently.
     *
     * Wire format: [4-byte big-endian length][JPEG bytes]
     */
    fun sendFrame(jpeg: ByteArray) {
        val len = jpeg.size

        // Write under lock — prevents the connection coroutine from swapping
        // the socket reference mid-write.
        synchronized(socketLock) {
            val os = outputStream ?: return   // not connected — drop frame

            try {
                // 4-byte big-endian length prefix
                lengthHeader[0] = (len shr 24).toByte()
                lengthHeader[1] = (len shr 16).toByte()
                lengthHeader[2] = (len shr  8).toByte()
                lengthHeader[3] = (len        ).toByte()

                os.write(lengthHeader)
                os.write(jpeg)
                // No flush() — TCP buffers handle batching; explicit flush stalls

                trackNetworkMetrics(len.toLong())

            } catch (e: Exception) {
                Log.w(TAG, "Send failed: ${e.message}")
                socketBroken = true
                // Don't close here — let the connection coroutine handle it
                // to avoid closing the socket from the analysis thread.
            }
        }
    }

    // =========================================================================
    // Connection loop (runs on IO dispatcher coroutine)
    // =========================================================================

    private suspend fun connectionLoop() = withContext(Dispatchers.IO) {
        while (isActive && running) {

            // If the previous socket broke, close it and wait before retrying.
            if (socketBroken) {
                closeSocket()
                socketBroken = false
                _state.value = _state.value.copy(
                    isConnected = false,
                    statusText  = "Reconnecting…",
                    networkFps  = 0f,
                    bytesPerSecond = 0L,
                )
                Log.w(TAG, "Connection lost — reconnecting in ${RECONNECT_DELAY}ms")
                delay(RECONNECT_DELAY)
            }

            // Skip if already healthy
            if (isSocketHealthy()) {
                delay(200)
                continue
            }

            // Attempt to connect
            Log.i(TAG, "Connecting to $serverIp:$serverPort …")
            try {
                val s = Socket()
                s.soTimeout = SO_TIMEOUT
                s.setTcpNoDelay(true)          // disable Nagle — minimises latency
                s.setSendBufferSize(256 * 1024) // 256 KB send buffer
                s.connect(InetSocketAddress(serverIp, serverPort), CONNECT_TIMEOUT)

                val os = s.getOutputStream()

                synchronized(socketLock) {
                    socket       = s
                    outputStream = os
                    socketBroken = false
                }

                Log.i(TAG, "Connected to $serverIp:$serverPort")
                _state.value = _state.value.copy(
                    isConnected = true,
                    statusText  = "Connected",
                    serverIp    = serverIp,
                    serverPort  = serverPort,
                )

            } catch (e: Exception) {
                Log.w(TAG, "Connect failed: ${e.message} — retrying in ${RECONNECT_DELAY}ms")
                closeSocket()
                _state.value = _state.value.copy(
                    isConnected = false,
                    statusText  = "Connection failed — retrying…",
                )
                delay(RECONNECT_DELAY)
            }
        }
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    private fun isSocketHealthy(): Boolean {
        val s = socket ?: return false
        return s.isConnected && !s.isClosed && !socketBroken
    }

    private fun closeSocket() {
        synchronized(socketLock) {
            runCatching { outputStream?.close() }
            runCatching { socket?.close() }
            outputStream = null
            socket       = null
        }
    }

    /**
     * Update rolling network FPS and bytes/sec metrics.
     * Both windows reset every 1 second.
     * Called from sendFrame() — always under socketLock.
     */
    private fun trackNetworkMetrics(bytesSent: Long) {
        val now = System.currentTimeMillis()

        // Network FPS
        netFpsCount++
        if (netFpsLastMs == 0L) netFpsLastMs = now
        val fpsElapsed = now - netFpsLastMs
        if (fpsElapsed >= 1_000L) {
            val fps = netFpsCount * 1_000f / fpsElapsed
            netFpsCount  = 0
            netFpsLastMs = now

            // Bytes/sec computed over the same window
            if (bytesFpsLastMs == 0L) bytesFpsLastMs = now
            val bpsElapsed = now - bytesFpsLastMs
            val bps = if (bpsElapsed > 0) bytesSentWindow * 1_000L / bpsElapsed else 0L
            bytesSentWindow = 0
            bytesFpsLastMs  = now

            // Publish to StateFlow (best-effort — may be slightly out of lock)
            _state.value = _state.value.copy(
                networkFps     = fps,
                bytesPerSecond = bps,
            )
        } else {
            bytesSentWindow += bytesSent
        }
    }
}
