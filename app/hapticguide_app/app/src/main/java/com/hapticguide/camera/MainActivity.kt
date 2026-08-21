package com.hapticguide.camera

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import android.view.KeyEvent
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.hapticguide.navigation.LocationTracker
import com.hapticguide.navigation.VoiceRecorder
import com.hapticguide.navigation.VolumeKeyVoiceTrigger

class MainActivity : ComponentActivity() {

    private lateinit var settingsManager:        SettingsManager
    private lateinit var tcpSender:              TcpFrameSender
    private lateinit var cameraManager:          CameraManager
    private lateinit var locationTracker:        LocationTracker
    private lateinit var voiceRecorder:          VoiceRecorder
    private lateinit var volumeKeyVoiceTrigger:  VolumeKeyVoiceTrigger

    private var isCameraPermissionGranted by mutableStateOf(false)
    private var isLocationPermissionGranted by mutableStateOf(false)
    private var isAudioPermissionGranted by mutableStateOf(false)

    private val requestPermissionsLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { grants ->
        isCameraPermissionGranted = grants[Manifest.permission.CAMERA] == true
        isLocationPermissionGranted =
            grants[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
            grants[Manifest.permission.ACCESS_COARSE_LOCATION] == true
        isAudioPermissionGranted = grants[Manifest.permission.RECORD_AUDIO] == true

        if (!isCameraPermissionGranted) {
            Toast.makeText(this, "Camera permission required.", Toast.LENGTH_LONG).show()
        }
        if (!isLocationPermissionGranted) {
            Toast.makeText(this, "Location permission required for navigation GPS.", Toast.LENGTH_LONG).show()
            locationTracker.reportPermissionDenied()
        } else {
            startGpsUpdates()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        settingsManager = SettingsManager(this)
        tcpSender       = TcpFrameSender()
        cameraManager   = CameraManager(
            context   = this,
            tcpSender = tcpSender,
        )
        locationTracker = LocationTracker(this)
        voiceRecorder   = VoiceRecorder(this)
        volumeKeyVoiceTrigger = VolumeKeyVoiceTrigger(
            voiceRecorder     = voiceRecorder,
            phoneHapticPlayer = locationTracker.phoneHapticPlayer,
        )

        checkPermissions()

        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    primary    = Color(0xFF64B5F6),
                    secondary  = Color(0xFF81C784),
                    background = Color(0xFF121212),
                ),
            ) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color    = MaterialTheme.colorScheme.background,
                ) {
                    StreamerScreen(
                        cameraManager         = cameraManager,
                        tcpSender             = tcpSender,
                        settingsManager       = settingsManager,
                        isPermissionGranted   = isCameraPermissionGranted,
                        onRequestPermission   = { checkPermissions() },
                        locationTracker       = locationTracker,
                        voiceRecorder         = voiceRecorder,
                        volumeKeyVoiceTrigger = volumeKeyVoiceTrigger,
                    )
                }
            }
        }
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN) {
            val handled = volumeKeyVoiceTrigger.handleKeyDown(keyCode, event?.repeatCount ?: 0)
            if (handled) return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN) {
            val handled = volumeKeyVoiceTrigger.handleKeyUp(keyCode)
            if (handled) return true
        }
        return super.onKeyUp(keyCode, event)
    }

    private fun checkPermissions() {
        isCameraPermissionGranted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.CAMERA,
        ) == PackageManager.PERMISSION_GRANTED
        isLocationPermissionGranted =
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED
        isAudioPermissionGranted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED

        val needed = mutableListOf<String>()
        if (!isCameraPermissionGranted) needed.add(Manifest.permission.CAMERA)
        if (!isLocationPermissionGranted) {
            needed.add(Manifest.permission.ACCESS_FINE_LOCATION)
            needed.add(Manifest.permission.ACCESS_COARSE_LOCATION)
        }
        if (!isAudioPermissionGranted) {
            needed.add(Manifest.permission.RECORD_AUDIO)
        }
        if (needed.isNotEmpty()) {
            requestPermissionsLauncher.launch(needed.toTypedArray())
        } else {
            startGpsUpdates()
        }
    }

    private fun startGpsUpdates() {
        locationTracker.start(
            settingsManager.getServerIp(),
            settingsManager.getHttpPort(),
        )
        voiceRecorder.bindBackend(
            settingsManager.getServerIp(),
            settingsManager.getHttpPort(),
        )
    }

    override fun onDestroy() {
        super.onDestroy()
        volumeKeyVoiceTrigger.reset()
        voiceRecorder.cancelRecording()
        locationTracker.stop()
        (locationTracker.serialTransport as? com.hapticguide.serial.HapticSerialManager)?.shutdown()
        cameraManager.shutdown()
    }
}

// ---------------------------------------------------------------------------
// Root screen
// ---------------------------------------------------------------------------

@Composable
fun StreamerScreen(
    cameraManager:         CameraManager,
    tcpSender:             TcpFrameSender,
    settingsManager:       SettingsManager,
    isPermissionGranted:   Boolean,
    onRequestPermission:   () -> Unit,
    locationTracker:       LocationTracker,
    voiceRecorder:         VoiceRecorder,
    volumeKeyVoiceTrigger: VolumeKeyVoiceTrigger,
) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val focusManager   = LocalFocusManager.current

    val senderState     by tcpSender.state.collectAsState()
    val cameraFps       by cameraManager.cameraFps.collectAsState()
    val gpsState        by locationTracker.state.collectAsState()
    val voiceState      by voiceRecorder.state.collectAsState()
    val activationState by volumeKeyVoiceTrigger.activationState.collectAsState()

    // Editable fields — initialised from persisted settings
    var serverIp    by remember { mutableStateOf(settingsManager.getServerIp()) }
    var serverPort  by remember { mutableStateOf(settingsManager.getServerPort().toString()) }
    var httpPort    by remember { mutableStateOf(settingsManager.getHttpPort().toString()) }

    Box(modifier = Modifier.fillMaxSize()) {

        // ── Camera preview ───────────────────────────────────────────────────
        if (isPermissionGranted) {
            AndroidView(
                factory = { ctx ->
                    PreviewView(ctx).apply {
                        scaleType = PreviewView.ScaleType.FILL_CENTER
                        cameraManager.startCamera(lifecycleOwner, this)
                    }
                },
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Column(
                modifier              = Modifier.fillMaxSize().padding(32.dp),
                verticalArrangement   = Arrangement.Center,
                horizontalAlignment   = Alignment.CenterHorizontally,
            ) {
                Text(
                    "Camera Permission Required",
                    style = MaterialTheme.typography.headlineSmall,
                    color = Color.White,
                )
                Spacer(Modifier.height(16.dp))
                Button(onClick = onRequestPermission) { Text("Grant Permission") }
            }
        }

        // ── Bottom panel ─────────────────────────────────────────────────────
        Column(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .padding(16.dp)
                .clip(RoundedCornerShape(20.dp))
                .background(Color.Black.copy(alpha = 0.75f))
                .padding(20.dp),
        ) {

            Text(
                text       = "HapticGuide Camera",
                fontSize   = 18.sp,
                fontWeight = FontWeight.Bold,
                color      = Color.White,
            )
            Spacer(Modifier.height(12.dp))

            // ── Status rows ──────────────────────────────────────────────────
            val connectedColor = if (senderState.isConnected) Color(0xFF4CAF50) else Color(0xFFEF5350)

            InfoRow("Connection",    senderState.statusText,          valueColor = connectedColor)
            InfoRow("Streaming",     if (cameraManager.isStreaming) "Active" else "Inactive")
            InfoRow("Camera FPS",    "%.1f".format(cameraFps))
            InfoRow("Network FPS",   "%.1f".format(senderState.networkFps))
            InfoRow("Throughput",    formatBytes(senderState.bytesPerSecond) + "/s")
            InfoRow("Server IP",     senderState.serverIp.ifEmpty { serverIp })
            InfoRow("Port",          if (senderState.serverPort > 0)
                                         senderState.serverPort.toString()
                                     else serverPort)
            val gpsColor = if (gpsState.statusText == "Active") Color(0xFF4CAF50)
                           else if (gpsState.statusText == "Permission denied" ||
                                    gpsState.statusText == "GPS unavailable") Color(0xFFEF5350)
                           else Color.White
            val gpsValue = if (gpsState.latitude != null && gpsState.longitude != null) {
                "${gpsState.statusText}  %.5f, %.5f".format(gpsState.latitude, gpsState.longitude)
            } else {
                gpsState.statusText
            }
            InfoRow("GPS", gpsValue, valueColor = gpsColor)

            val voiceColor = if (activationState == com.hapticguide.navigation.VoiceActivationState.RECORDING || voiceState.isRecording) Color(0xFFFF5722)
                             else if (activationState == com.hapticguide.navigation.VoiceActivationState.ARMED) Color(0xFFFFB74D)
                             else if (voiceState.isProcessing) Color(0xFF64B5F6)
                             else Color.White
            val voiceMsg = if (activationState != com.hapticguide.navigation.VoiceActivationState.IDLE) {
                "Vol Chord: ${activationState.statusText}"
            } else {
                voiceState.statusMessage
            }
            InfoRow("Voice Trigger", voiceMsg, valueColor = voiceColor)
            if (!voiceState.lastDestination.isNullOrEmpty()) {
                InfoRow("Destination", voiceState.lastDestination ?: "", valueColor = Color(0xFF81C784))
            }

            val serialState by locationTracker.serialTransport.connectionState.collectAsState()
            val serialColor = when (serialState) {
                com.hapticguide.serial.SerialConnectionState.CONNECTED -> Color(0xFF4CAF50)
                com.hapticguide.serial.SerialConnectionState.CONNECTING -> Color(0xFFFFB74D)
                com.hapticguide.serial.SerialConnectionState.ERROR -> Color(0xFFEF5350)
                com.hapticguide.serial.SerialConnectionState.DISCONNECTED -> Color.LightGray
            }
            InfoRow("ESP32 Serial", serialState.statusText, valueColor = serialColor)

            Spacer(Modifier.height(12.dp))
            HorizontalDivider(color = Color.White.copy(alpha = 0.15f))
            Spacer(Modifier.height(12.dp))

            // ── Editable server address ──────────────────────────────────────
            Row(
                modifier              = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value         = serverIp,
                    onValueChange = {
                        serverIp = it
                        settingsManager.setServerIp(it)
                        val http = httpPort.toIntOrNull() ?: settingsManager.getHttpPort()
                        locationTracker.bindBackend(it.trim(), http)
                        voiceRecorder.bindBackend(it.trim(), http)
                    },
                    label         = { Text("Server IP", color = Color.LightGray) },
                    singleLine    = true,
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Ascii,
                        imeAction    = ImeAction.Next,
                    ),
                    colors  = tcpFieldColors(),
                    modifier = Modifier.weight(2f),
                )
                OutlinedTextField(
                    value         = serverPort,
                    onValueChange = {
                        serverPort = it
                        it.toIntOrNull()?.let { p -> settingsManager.setServerPort(p) }
                    },
                    label         = { Text("Port", color = Color.LightGray) },
                    singleLine    = true,
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Number,
                        imeAction    = ImeAction.Done,
                    ),
                    keyboardActions = KeyboardActions(onDone = { focusManager.clearFocus() }),
                    colors  = tcpFieldColors(),
                    modifier = Modifier.weight(1f),
                )
            }

            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value         = httpPort,
                onValueChange = {
                    httpPort = it
                    it.toIntOrNull()?.let { p ->
                        settingsManager.setHttpPort(p)
                        locationTracker.bindBackend(serverIp.trim(), p)
                        voiceRecorder.bindBackend(serverIp.trim(), p)
                    }
                },
                label         = { Text("HTTP Port (GPS/Voice)", color = Color.LightGray) },
                singleLine    = true,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Number,
                    imeAction    = ImeAction.Done,
                ),
                keyboardActions = KeyboardActions(onDone = { focusManager.clearFocus() }),
                colors  = tcpFieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(12.dp))

            // ── Voice Input Button ───────────────────────────────────────────
            Button(
                onClick = {
                    if (voiceState.isRecording) {
                        voiceRecorder.stopRecordingAndSend()
                    } else {
                        voiceRecorder.startRecording()
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (voiceState.isRecording) "🔴 STOP RECORDING & SEND" else "🎤 VOICE DESTINATION (TAP TO SPEAK)")
            }

            Spacer(Modifier.height(8.dp))

            // ── START / STOP buttons ─────────────────────────────────────────
            Row(
                modifier              = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Button(
                    onClick = {
                        focusManager.clearFocus()
                        val port = serverPort.toIntOrNull() ?: settingsManager.getServerPort()
                        val http = httpPort.toIntOrNull() ?: settingsManager.getHttpPort()
                        locationTracker.start(serverIp.trim(), http)
                        voiceRecorder.bindBackend(serverIp.trim(), http)
                        cameraManager.startStreaming(serverIp.trim(), port)
                    },
                    modifier = Modifier.weight(1f),
                    enabled  = !cameraManager.isStreaming,
                ) {
                    Text("START")
                }
                Button(
                    onClick  = { cameraManager.stopStreaming() },
                    modifier = Modifier.weight(1f),
                    enabled  = cameraManager.isStreaming,
                ) {
                    Text("STOP")
                }
            }

            Spacer(Modifier.height(10.dp))

            // ── Manual Haptic Test / Debug Row ───────────────────────────────
            Text(
                "Manual Haptic Test (ESP32 Serial):",
                fontSize = 11.sp,
                color = Color.LightGray,
            )
            Spacer(Modifier.height(4.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Button(
                    onClick = { locationTracker.serialTransport.send("START") },
                    modifier = Modifier.weight(1.1f),
                ) {
                    Text("START", fontSize = 9.sp)
                }
                Button(
                    onClick = { locationTracker.serialTransport.send("LEFT") },
                    modifier = Modifier.weight(1f),
                ) {
                    Text("LEFT", fontSize = 9.sp)
                }
                Button(
                    onClick = { locationTracker.serialTransport.send("FRONT") },
                    modifier = Modifier.weight(1f),
                ) {
                    Text("FRONT", fontSize = 9.sp)
                }
                Button(
                    onClick = { locationTracker.serialTransport.send("RIGHT") },
                    modifier = Modifier.weight(1f),
                ) {
                    Text("RIGHT", fontSize = 9.sp)
                }
                Button(
                    onClick = { locationTracker.serialTransport.send("STOP") },
                    modifier = Modifier.weight(1f),
                ) {
                    Text("STOP", fontSize = 9.sp)
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Composable helpers
// ---------------------------------------------------------------------------

@Composable
private fun InfoRow(
    label:      String,
    value:      String,
    valueColor: Color = Color.White,
) {
    Row(
        modifier              = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment     = Alignment.CenterVertically,
    ) {
        Text(label, fontSize = 12.sp, color = Color.LightGray)
        Text(value, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = valueColor)
    }
    Spacer(Modifier.height(4.dp))
}

@Composable
private fun tcpFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor     = Color.White,
    unfocusedTextColor   = Color.White,
    focusedBorderColor   = Color(0xFF64B5F6),
    unfocusedBorderColor = Color.White.copy(alpha = 0.35f),
    cursorColor          = Color(0xFF64B5F6),
)

private fun formatBytes(bps: Long): String = when {
    bps >= 1_000_000 -> "%.1f MB".format(bps / 1_000_000.0)
    bps >= 1_000     -> "%.1f KB".format(bps / 1_000.0)
    else             -> "$bps B"
}
