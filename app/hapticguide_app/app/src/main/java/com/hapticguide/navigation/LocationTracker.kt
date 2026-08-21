package com.hapticguide.navigation

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Looper
import android.util.Log
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import com.hapticguide.serial.HapticSerialManager
import com.hapticguide.serial.HapticSerialTransport
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Phone GPS → FastAPI /nav/gps.
 * Isolated from CameraX / TCP streaming. Does not drive obstacle PWM.
 */
class LocationTracker(
    private val context: Context,
    private val httpClient: NavHttpClient = NavHttpClient(),
    val serialTransport: HapticSerialTransport = HapticSerialManager(context),
) : LocationListener {

    data class GpsUiState(
        val statusText: String = "Idle",
        val isActive: Boolean = false,
        val latitude: Double? = null,
        val longitude: Double? = null,
        val decision: NavigationDecision? = null,
    )

    companion object {
        private const val TAG = "LocationTracker"
        private const val MIN_INTERVAL_MS = 1000L
        private const val MIN_DISTANCE_M = 0f
        private const val STALE_AFTER_MS = 8_000L
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val locationManager =
        context.getSystemService(Context.LOCATION_SERVICE) as LocationManager

    val phoneHapticPlayer = PhoneHapticPlayer(context)
    val navigationEventHandler = NavigationEventHandler(phoneHapticPlayer, serialTransport)

    private val _state = MutableStateFlow(GpsUiState())
    val state: StateFlow<GpsUiState> = _state.asStateFlow()

    @Volatile private var started = false
    @Volatile private var lastFixAtMs = 0L
    @Volatile private var startedAtMs = 0L
    @Volatile private var lastReportedFault: String? = null
    private var staleWatch: Job? = null
    private var progressWatch: Job? = null

    fun bindBackend(ip: String, httpPort: Int) {
        httpClient.serverIp = ip.trim()
        httpClient.httpPort = httpPort
    }

    fun handleExternalDecision(decision: NavigationDecision) {
        _state.value = _state.value.copy(decision = decision)
        navigationEventHandler.handleDecision(decision)
    }

    fun hasPermission(): Boolean {
        val fine = ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        val coarse = ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_COARSE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        return fine || coarse
    }

    fun reportPermissionDenied() {
        stop()
        lastReportedFault = "PERMISSION_DENIED"
        _state.value = GpsUiState(statusText = "Permission denied", isActive = false)
        scope.launch {
            httpClient.postFault("PERMISSION_DENIED", "Location permission denied")
        }
    }

    fun start(ip: String, httpPort: Int) {
        bindBackend(ip, httpPort)
        if (!hasPermission()) {
            reportPermissionDenied()
            return
        }

        val gpsOn = locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)
        val netOn = locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        if (!gpsOn && !netOn) {
            lastReportedFault = "GPS_UNAVAILABLE"
            _state.value = GpsUiState(statusText = "GPS unavailable", isActive = false)
            scope.launch {
                httpClient.postFault("GPS_UNAVAILABLE", "No location provider enabled")
            }
            return
        }

        if (started) {
            publishLastKnown()
            return
        }

        try {
            if (gpsOn) {
                locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER,
                    MIN_INTERVAL_MS,
                    MIN_DISTANCE_M,
                    this,
                    Looper.getMainLooper(),
                )
            }
            if (netOn) {
                locationManager.requestLocationUpdates(
                    LocationManager.NETWORK_PROVIDER,
                    MIN_INTERVAL_MS,
                    MIN_DISTANCE_M,
                    this,
                    Looper.getMainLooper(),
                )
            }
            if (locationManager.isProviderEnabled(LocationManager.PASSIVE_PROVIDER)) {
                locationManager.requestLocationUpdates(
                    LocationManager.PASSIVE_PROVIDER,
                    MIN_INTERVAL_MS,
                    MIN_DISTANCE_M,
                    this,
                    Looper.getMainLooper(),
                )
            }
            started = true
            startedAtMs = System.currentTimeMillis()
            lastFixAtMs = 0L
            lastReportedFault = null
            _state.value = _state.value.copy(statusText = "Acquiring…", isActive = true)
            publishLastKnown()
            startStaleWatch()
            startProgressWatch()
            serialTransport.connect()
            Log.i(TAG, "Location updates started")
        } catch (e: SecurityException) {
            reportPermissionDenied()
        }
    }

    fun stop() {
        staleWatch?.cancel()
        staleWatch = null
        progressWatch?.cancel()
        progressWatch = null
        if (started) {
            runCatching { locationManager.removeUpdates(this) }
            started = false
        }
        navigationEventHandler.reset()
        _state.value = _state.value.copy(isActive = false, statusText = "Stopped")
    }

    override fun onLocationChanged(location: Location) {
        if (!started) return
        lastFixAtMs = System.currentTimeMillis()
        lastReportedFault = null
        val acc = if (location.hasAccuracy()) location.accuracy else null
        _state.value = _state.value.copy(
            statusText = "Active",
            isActive = true,
            latitude = location.latitude,
            longitude = location.longitude,
        )
        scope.launch {
            val response = httpClient.postFix(location.latitude, location.longitude, acc)
            val decision = NavigationDecision.fromJsonObject(response)
            _state.value = _state.value.copy(decision = decision)
            navigationEventHandler.handleDecision(decision)
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit

    override fun onProviderEnabled(provider: String) {
        if (started) {
            _state.value = _state.value.copy(statusText = "Acquiring…", isActive = true)
        }
    }

    override fun onProviderDisabled(provider: String) {
        val gpsOn = locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)
        val netOn = locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        if (!gpsOn && !netOn) {
            _state.value = _state.value.copy(statusText = "GPS unavailable", isActive = false)
            if (lastReportedFault != "GPS_UNAVAILABLE") {
                lastReportedFault = "GPS_UNAVAILABLE"
                scope.launch {
                    httpClient.postFault("GPS_UNAVAILABLE", "Location providers disabled")
                }
            }
        }
    }

    private fun publishLastKnown() {
        if (!hasPermission()) return
        val last = runCatching {
            locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
                ?: locationManager.getLastKnownLocation(LocationManager.PASSIVE_PROVIDER)
        }.getOrNull() ?: return
        onLocationChanged(last)
    }

    private fun startStaleWatch() {
        staleWatch?.cancel()
        staleWatch = scope.launch {
            while (isActive && started) {
                delay(2_000)
                val last = lastFixAtMs
                val now = System.currentTimeMillis()
                if (last == 0L || now - last > 3_000L) {
                    // Fallback to last known position if no fresh callback fix arrived
                    publishLastKnown()
                }
                val freshLast = lastFixAtMs
                if (freshLast == 0L) {
                    if (now - startedAtMs > STALE_AFTER_MS) {
                        if (lastReportedFault != "LOCATION_UNAVAILABLE") {
                            lastReportedFault = "LOCATION_UNAVAILABLE"
                            httpClient.postFault("LOCATION_UNAVAILABLE", "Waiting for first GPS fix")
                        }
                        _state.value = _state.value.copy(statusText = "Unavailable")
                    }
                } else if (now - freshLast > STALE_AFTER_MS) {
                    if (lastReportedFault != "STALE") {
                        lastReportedFault = "STALE"
                        httpClient.postFault("STALE", "Location older than ${STALE_AFTER_MS}ms")
                    }
                    _state.value = _state.value.copy(
                        statusText = "Stale",
                        isActive = true,
                    )
                }
            }
        }
    }

    private fun startProgressWatch() {
        progressWatch?.cancel()
        progressWatch = scope.launch {
            while (isActive && started) {
                delay(1_000)
                val json = httpClient.getProgress()
                if (json != null) {
                    val decision = NavigationDecision.fromJsonObject(json)
                    if (decision.active) {
                        _state.value = _state.value.copy(decision = decision)
                        navigationEventHandler.handleDecision(decision)
                    }
                }
            }
        }
    }
}
