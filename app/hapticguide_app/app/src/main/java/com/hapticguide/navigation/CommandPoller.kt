package com.hapticguide.navigation

import android.util.Log
import com.hapticguide.serial.HapticSerialTransport
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
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * CommandPoller
 * -------------
 * Periodically polls FastAPI GET /cmd at 20 Hz (every 50ms), matching live_dashboard.html.
 * Parses 4-axis motor commands {"left": L, "front": F, "right": R, "back": B}.
 *
 * Actions on non-zero command:
 * 1. Triggers local phone vibration (PhoneHapticPlayer) for immediate feedback.
 * 2. Transmits serial commands (M,L,F,R,B or LEFT/RIGHT/FRONT/STOP) to the ESP32 belt via HapticSerialTransport.
 */
class CommandPoller(
    private val phoneHapticPlayer: PhoneHapticPlayer,
    private val serialTransport: HapticSerialTransport,
) {
    companion object {
        private const val TAG = "CommandPoller"
        private const val POLL_INTERVAL_MS = 50L // 20 Hz
        private const val TIMEOUT_MS = 800
    }

    data class CommandState(
        val isPolling: Boolean = false,
        val left: Int = 0,
        val front: Int = 0,
        val right: Int = 0,
        val back: Int = 0,
        val lastSuccessMs: Long = 0L,
        val errorMessage: String? = null,
    )

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var pollJob: Job? = null

    @Volatile var serverIp: String = ""
    @Volatile var httpPort: Int = 8000

    private val _state = MutableStateFlow(CommandState())
    val state: StateFlow<CommandState> = _state.asStateFlow()

    @Volatile private var lastSentCmd: String = ""
    @Volatile private var lastVibratedMs: Long = 0L
    @Volatile private var frontActive: Boolean = false
    @Volatile private var lastVibrationRefreshMs: Long = 0L
    @Volatile private var consecutiveZeroFrontPolls: Int = 0

    fun bindBackend(ip: String, port: Int) {
        serverIp = ip.trim()
        httpPort = port
    }

    fun start(ip: String, port: Int) {
        bindBackend(ip, port)
        if (pollJob?.isActive == true) return

        _state.value = _state.value.copy(isPolling = true, errorMessage = null)
        pollJob = scope.launch {
            Log.i(TAG, "CommandPoller started polling GET /cmd at http://$serverIp:$httpPort/cmd ($POLL_INTERVAL_MS ms interval)")
            while (isActive) {
                pollOnce()
                delay(POLL_INTERVAL_MS)
            }
        }
    }

    fun stop() {
        pollJob?.cancel()
        pollJob = null
        if (frontActive) {
            frontActive = false
            consecutiveZeroFrontPolls = 0
            phoneHapticPlayer.stopVibration()
        }
        _state.value = CommandState(isPolling = false)
        Log.i(TAG, "CommandPoller stopped.")
    }

    private fun pollOnce() {
        val ip = serverIp.trim()
        if (ip.isEmpty() || httpPort <= 0) return

        var conn: HttpURLConnection? = null
        try {
            val url = URL("http://$ip:$httpPort/cmd")
            conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = TIMEOUT_MS
                readTimeout = TIMEOUT_MS
                setRequestProperty("Accept", "application/json")
            }

            if (conn.responseCode == 200) {
                val jsonStr = conn.inputStream.use { String(it.readBytes(), Charsets.UTF_8) }
                val obj = JSONObject(jsonStr)
                val left = obj.optInt("left", 0)
                val front = obj.optInt("front", 0)
                val right = obj.optInt("right", 0)
                val back = obj.optInt("back", 0)

                Log.d(TAG, "Poll result: left=$left front=$front right=$right back=$back")

                val now = System.currentTimeMillis()
                _state.value = _state.value.copy(
                    isPolling = true,
                    left = left,
                    front = front,
                    right = right,
                    back = back,
                    lastSuccessMs = now,
                    errorMessage = null,
                )

                dispatchCommand(left, front, right, back, now)
            } else {
                _state.value = _state.value.copy(errorMessage = "HTTP ${conn.responseCode}")
            }
        } catch (e: Exception) {
            // Silently log network dropouts to avoid spamming logcat at 20 Hz
            _state.value = _state.value.copy(errorMessage = e.message ?: "Network error")
        } finally {
            conn?.disconnect()
        }
    }

    @Volatile private var lastPingMs: Long = 0L

    private fun dispatchCommand(leftPwm: Int, frontPwm: Int, rightPwm: Int, backPwm: Int, nowMs: Long) {
        // User request: ONLY vibrate when F is exactly 255.
        // If F is anything else (especially 0), stop vibration immediately.
        val isFrontMax = (frontPwm == 255)
        val isLeft = leftPwm > 0
        val isRight = rightPwm > 0

        if (isFrontMax) {
            consecutiveZeroFrontPolls = 0
            if (!frontActive) {
                // Obstacle at max intensity -> start continuous vibration
                frontActive = true
                lastVibrationRefreshMs = nowMs
                Log.i(TAG, "Front obstacle MAX (255) detected -> starting continuous phone vibration")
                phoneHapticPlayer.startContinuousVibration()
            } else if (nowMs - lastVibrationRefreshMs > 5000) {
                // Safety refresh every 5s
                lastVibrationRefreshMs = nowMs
                phoneHapticPlayer.startContinuousVibration()
            }
        } else {
            // F is not 255 (could be 0 or some intermediate value) -> stop vibration immediately
            if (frontActive) {
                frontActive = false
                consecutiveZeroFrontPolls = 0
                Log.i(TAG, "Front obstacle NOT 255 (value: $frontPwm) -> stopping phone vibration")
                phoneHapticPlayer.stopVibration()
            }
        }

        // 2. ESP32 Serial Transmission (LEFT/RIGHT obstacles drive belt motors with PWM 150)
        val leftVal = if (isLeft) 150 else 0
        val rightVal = if (isRight) 150 else 0
        val cmdString = "M,$leftVal,0,$rightVal,0"

        if (cmdString != lastSentCmd || isLeft || isRight) {
            lastSentCmd = cmdString
            if (serialTransport.isConnected()) {
                serialTransport.send(cmdString)
            }
        } else if (!isLeft && !isRight && serialTransport.isConnected() && nowMs - lastPingMs > 3000) {
            // Heartbeat PING every 3 seconds when idle to refresh serial debug Rx on screen
            lastPingMs = nowMs
            serialTransport.send("PING")
        }
    }
}
