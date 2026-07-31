package com.hapticguide.camera

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope

/**
 * MainActivity requests runtime camera permissions, initializes the app modules,
 * and launches the Jetpack Compose User Interface.
 */
class MainActivity : ComponentActivity() {

    private lateinit var settingsManager: SettingsManager
    private lateinit var frameUploader: FrameUploader
    private lateinit var cameraManager: CameraManager

    // Reactive Compose states for UI metrics and system logs
    private var connectionStatus by mutableStateOf("Initializing...")
    private var totalFramesSent by mutableStateOf(0)
    private var currentFps by mutableStateOf(0.0f)
    private var isCameraPermissionGranted by mutableStateOf(false)

    // Permission request launcher
    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted: Boolean ->
        isCameraPermissionGranted = isGranted
        if (isGranted) {
            connectionStatus = "Permission Granted. Starting camera..."
        } else {
            connectionStatus = "Camera Permission Denied"
            Toast.makeText(this, "Camera permission is required to stream frames.", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Keep the screen turned on while this application is in the foreground
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Initialize managers
        settingsManager = SettingsManager(this)
        frameUploader = FrameUploader(lifecycleScope)
        cameraManager = CameraManager(
            context = this,
            frameUploader = frameUploader,
            settingsManager = settingsManager,
            onMetricsUpdated = { frames, fps ->
                totalFramesSent = frames
                currentFps = fps
            },
            onConnectionStatusUpdated = { status ->
                connectionStatus = status
            }
        )

        // Evaluate permission on launch
        checkPermission()

        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    primary = Color(0xFF64B5F6),
                    secondary = Color(0xFF81C784),
                    background = Color(0xFF121212)
                )
            ) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    CameraStreamerScreen(
                        connectionStatus = connectionStatus,
                        framesSent = totalFramesSent,
                        fps = currentFps,
                        isPermissionGranted = isCameraPermissionGranted,
                        settingsManager = settingsManager,
                        cameraManager = cameraManager,
                        onRequestPermission = { checkPermission() }
                    )
                }
            }
        }
    }

    private fun checkPermission() {
        if (ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.CAMERA
            ) == PackageManager.PERMISSION_GRANTED
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

@Composable
fun CameraStreamerScreen(
    connectionStatus: String,
    framesSent: Int,
    fps: Float,
    isPermissionGranted: Boolean,
    settingsManager: SettingsManager,
    cameraManager: CameraManager,
    onRequestPermission: () -> Unit
) {
    val lifecycleOwner = LocalLifecycleOwner.current
    var serverIp by remember { mutableStateOf(settingsManager.getServerIp()) }
    val focusManager = LocalFocusManager.current

    Box(modifier = Modifier.fillMaxSize()) {
        if (isPermissionGranted) {
            // 1. Camera preview background (Requirement 1 & 10)
            AndroidView(
                factory = { ctx ->
                    PreviewView(ctx).apply {
                        scaleType = PreviewView.ScaleType.FILL_CENTER
                        cameraManager.startCamera(lifecycleOwner, this)
                    }
                },
                modifier = Modifier.fillMaxSize()
            )
        } else {
            // Permission request display
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(32.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(
                    text = "Camera Permission Required",
                    style = MaterialTheme.typography.headlineSmall,
                    color = Color.White
                )
                Spacer(modifier = Modifier.height(16.dp))
                Button(onClick = onRequestPermission) {
                    Text("Grant Permission")
                }
            }
        }

        // 2. Control overlay panel (Requirement 10)
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp)
        ) {
            Column(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(24.dp))
                    .background(Color.Black.copy(alpha = 0.7f)) // Translucent overlay card
                    .padding(24.dp)
            ) {
                // Header with status indicator
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text = "Camera Streamer",
                        fontSize = 20.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color.White
                    )

                    // Smooth status indicator pulse
                    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
                    val alpha by infiniteTransition.animateFloat(
                        initialValue = 0.3f,
                        targetValue = 1.0f,
                        animationSpec = infiniteRepeatable(
                            animation = tween(800, easing = LinearEasing),
                            repeatMode = RepeatMode.Reverse
                        ),
                        label = "pulseAlpha"
                    )

                    // Compute dynamic status color mapping
                    val statusColor = when {
                        connectionStatus.startsWith("Connected") || connectionStatus.startsWith("Streaming") -> Color(0xFF2ECC71)
                        connectionStatus.startsWith("Error") -> Color(0xFFE74C3C)
                        else -> Color(0xFFF1C40F)
                    }

                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Box(
                            modifier = Modifier
                                .size(10.dp)
                                .clip(CircleShape)
                                .background(statusColor.copy(alpha = alpha))
                        )
                        Text(
                            text = connectionStatus,
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                            color = statusColor
                        )
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))
                HorizontalDivider(color = Color.White.copy(alpha = 0.2f))
                Spacer(modifier = Modifier.height(16.dp))

                // Stream details row
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            text = "Streaming FPS",
                            fontSize = 12.sp,
                            color = Color.LightGray
                        )
                        Text(
                            text = String.format("%.1f", fps),
                            fontSize = 24.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color.White
                        )
                    }
                }

                Spacer(modifier = Modifier.height(20.dp))

                // Server Address inputs (Requirement 11 & User customization request)
                OutlinedTextField(
                    value = serverIp,
                    onValueChange = {
                        serverIp = it
                        settingsManager.setServerIp(it) // Instantly commit change
                    },
                    label = { Text("Server Address (IP:PORT/path)", color = Color.LightGray) },
                    placeholder = { Text("e.g. 192.168.1.15:8000/receive", color = Color.Gray) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Ascii,
                        imeAction = ImeAction.Done
                    ),
                    keyboardActions = KeyboardActions(
                        onDone = { focusManager.clearFocus() }
                    ),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = Color.White,
                        unfocusedTextColor = Color.White,
                        focusedBorderColor = Color(0xFF64B5F6),
                        unfocusedBorderColor = Color.White.copy(alpha = 0.4f),
                        cursorColor = Color(0xFF64B5F6)
                    ),
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
    }
}
