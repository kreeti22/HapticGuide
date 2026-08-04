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
import androidx.lifecycle.compose.LocalLifecycleOwner

class MainActivity : ComponentActivity() {

    private lateinit var settingsManager: SettingsManager
    private lateinit var tcpSender:       TcpFrameSender
    private lateinit var cameraManager:   CameraManager

    private var isCameraPermissionGranted by mutableStateOf(false)

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { isGranted ->
        isCameraPermissionGranted = isGranted
        if (!isGranted) {
            Toast.makeText(this, "Camera permission required.", Toast.LENGTH_LONG).show()
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

        checkPermission()

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
                        cameraManager       = cameraManager,
                        tcpSender           = tcpSender,
                        settingsManager     = settingsManager,
                        isPermissionGranted = isCameraPermissionGranted,
                        onRequestPermission = { checkPermission() },
                    )
                }
            }
        }
    }

    private fun checkPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED
        ) {
            isCameraPermissionGranted = true
        } else {
            requestPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraManager.shutdown()
    }
}

// ---------------------------------------------------------------------------
// Root screen
// ---------------------------------------------------------------------------

@Composable
fun StreamerScreen(
    cameraManager:       CameraManager,
    tcpSender:           TcpFrameSender,
    settingsManager:     SettingsManager,
    isPermissionGranted: Boolean,
    onRequestPermission: () -> Unit,
) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val focusManager   = LocalFocusManager.current

    val senderState by tcpSender.state.collectAsState()
    val cameraFps   by cameraManager.cameraFps.collectAsState()

    // Editable fields — initialised from persisted settings
    var serverIp   by remember { mutableStateOf(settingsManager.getServerIp()) }
    var serverPort by remember { mutableStateOf(settingsManager.getServerPort().toString()) }

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

            Spacer(Modifier.height(12.dp))

            // ── START / STOP buttons ─────────────────────────────────────────
            Row(
                modifier              = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Button(
                    onClick = {
                        focusManager.clearFocus()
                        val port = serverPort.toIntOrNull() ?: settingsManager.getServerPort()
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
