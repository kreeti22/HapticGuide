package com.hapticguide.serial

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.util.Log
import com.hapticguide.navigation.NavigationEvent
import com.hoho.android.usbserial.driver.UsbSerialPort
import com.hoho.android.usbserial.driver.UsbSerialProber
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Robust USB-OTG Serial Transport powered by usb-serial-for-android.
 *
 * Provides tested driver support & correct 115200 8N1 baud rate setup for:
 * - CP210x (vendorId 0x10C4)
 * - CH340 / CH341 (vendorId 0x1A86)
 * - FTDI (vendorId 0x0403)
 * - PL2303 (vendorId 0x067B)
 * - ESP32 CDC-ACM (vendorId 0x303A)
 */
class UsbSerialTransport(
    private val context: Context,
    private val baudRate: Int = 115200,
) : HapticSerialTransport {

    companion object {
        private const val TAG = "HapticSerialTransport"
        private const val ACTION_USB_PERMISSION = "com.hapticguide.USB_PERMISSION"
        private const val TIMEOUT_MS = 1000
    }

    private val usbManager = context.getSystemService(Context.USB_SERVICE) as UsbManager

    private val _connectionState = MutableStateFlow(SerialConnectionState.DISCONNECTED)
    override val connectionState: StateFlow<SerialConnectionState> = _connectionState.asStateFlow()

    private val _lastRxMessage = MutableStateFlow("")
    override val lastRxMessage: StateFlow<String> = _lastRxMessage.asStateFlow()

    private var serialPort: UsbSerialPort? = null
    private var currentDevice: UsbDevice? = null
    private val portLock = Any()

    private var readJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO)

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                ACTION_USB_PERMISSION -> {
                    val device: UsbDevice? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        intent.getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
                    } else {
                        @Suppress("DEPRECATION")
                        intent.getParcelableExtra(UsbManager.EXTRA_DEVICE)
                    }
                    val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    val targetDev = device ?: currentDevice ?: getFirstAvailableUsbDevice()
                    if (granted && targetDev != null) {
                        Log.i(TAG, "USB Permission granted for device: ${targetDev.deviceName}")
                        openDevice(targetDev)
                    } else {
                        Log.w(TAG, "USB Permission denied or target device null")
                        _connectionState.value = SerialConnectionState.ERROR
                    }
                }
                UsbManager.ACTION_USB_DEVICE_ATTACHED -> {
                    Log.i(TAG, "USB Device attached, attempting auto-connect")
                    connect()
                }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    Log.i(TAG, "USB Device detached")
                    disconnect()
                }
            }
        }
    }

    init {
        val filter = IntentFilter().apply {
            addAction(ACTION_USB_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(usbReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            context.registerReceiver(usbReceiver, filter)
        }
    }

    private fun getFirstAvailableUsbDevice(): UsbDevice? {
        val availableDrivers = UsbSerialProber.getDefaultProber().findAllDrivers(usbManager)
        if (availableDrivers.isNotEmpty()) {
            return availableDrivers[0].device
        }
        return usbManager.deviceList.values.firstOrNull()
    }

    override fun connect(): Boolean {
        if (isConnected()) {
            Log.d(TAG, "Already connected to USB serial port")
            return true
        }

        try {
            val availableDrivers = UsbSerialProber.getDefaultProber().findAllDrivers(usbManager)
            val driver = availableDrivers.firstOrNull() ?: run {
                Log.d(TAG, "No USB serial drivers found")
                _connectionState.value = SerialConnectionState.DISCONNECTED
                return false
            }

            val device = driver.device
            currentDevice = device

            if (!usbManager.hasPermission(device)) {
                _connectionState.value = SerialConnectionState.CONNECTING
                Log.i(TAG, "Requesting USB permission for ${device.deviceName} (VID: ${device.vendorId}, PID: ${device.productId})")
                val pIntent = Intent(ACTION_USB_PERMISSION).apply {
                    setPackage(context.packageName)
                }
                val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
                } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    PendingIntent.FLAG_UPDATE_CURRENT
                } else {
                    0
                }
                val permissionIntent = PendingIntent.getBroadcast(
                    context,
                    0,
                    pIntent,
                    flags
                )
                usbManager.requestPermission(device, permissionIntent)
                return false
            }

            return openDevice(device)
        } catch (e: Exception) {
            Log.e(TAG, "USB connect error: ${e.message}", e)
            _connectionState.value = SerialConnectionState.ERROR
            return false
        }
    }

    private fun openDevice(device: UsbDevice): Boolean {
        try {
            val driver = UsbSerialProber.getDefaultProber().probeDevice(device)
                ?: UsbSerialProber.getDefaultProber().findAllDrivers(usbManager).firstOrNull { it.device == device }

            if (driver == null || driver.ports.isEmpty()) {
                Log.e(TAG, "No USB serial driver/ports found for device")
                _connectionState.value = SerialConnectionState.ERROR
                return false
            }

            val connection = usbManager.openDevice(device)
                ?: run {
                    Log.e(TAG, "Failed to open UsbManager device connection")
                    _connectionState.value = SerialConnectionState.ERROR
                    return false
                }

            val port = driver.ports[0]
            port.open(connection)
            port.setParameters(baudRate, 8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE)
            port.dtr = true
            port.rts = true

            synchronized(portLock) {
                serialPort = port
            }

            _connectionState.value = SerialConnectionState.CONNECTED
            Log.i(TAG, "SERIAL CONNECTED: ${device.deviceName} (VID:${device.vendorId}, PID:${device.productId}) @ $baudRate baud 8N1")

            startReadLoop()
            scope.launch {
                delay(300)
                send("PING")
            }

            return true
        } catch (e: Exception) {
            Log.e(TAG, "Error opening USB serial port: ${e.message}", e)
            _connectionState.value = SerialConnectionState.ERROR
            return false
        }
    }

    private fun startReadLoop() {
        readJob?.cancel()
        readJob = scope.launch {
            val buffer = ByteArray(256)
            var sb = StringBuilder()
            while (isActive && isConnected()) {
                val port = serialPort
                if (port != null) {
                    try {
                        val bytesRead = port.read(buffer, TIMEOUT_MS)
                        if (bytesRead > 0) {
                            val text = String(buffer, 0, bytesRead, Charsets.UTF_8)
                            for (ch in text) {
                                if (ch == '\n' || ch == '\r') {
                                    val line = sb.toString().trim()
                                    if (line.isNotEmpty()) {
                                        Log.i(TAG, "SERIAL RX: $line")
                                        _lastRxMessage.value = line
                                    }
                                    sb = StringBuilder()
                                } else {
                                    sb.append(ch)
                                }
                            }
                        }
                    } catch (e: Exception) {
                        Log.d(TAG, "Read loop exception: ${e.message}")
                    }
                }
                delay(25)
            }
        }
    }

    override fun disconnect() {
        readJob?.cancel()
        readJob = null
        synchronized(portLock) {
            try {
                serialPort?.close()
            } catch (e: Exception) {
                Log.w(TAG, "Error closing USB serial port: ${e.message}")
            } finally {
                serialPort = null
                currentDevice = null
                _connectionState.value = SerialConnectionState.DISCONNECTED
                _lastRxMessage.value = ""
                Log.i(TAG, "SERIAL DISCONNECTED")
            }
        }
    }

    override fun send(command: String): Boolean {
        val cleanCmd = command.trim()
        if (cleanCmd.isEmpty()) return false

        val payload = "$cleanCmd\n".toByteArray(Charsets.UTF_8)

        synchronized(portLock) {
            val port = serialPort
            if (port == null || !isConnected()) {
                Log.w(TAG, "Cannot send '$cleanCmd': USB Serial not connected")
                return false
            }

            try {
                port.write(payload, TIMEOUT_MS)
                Log.i(TAG, "SERIAL TX: $cleanCmd")
                return true
            } catch (e: Exception) {
                Log.e(TAG, "Failed to send command '$cleanCmd': ${e.message}", e)
                return false
            }
        }
    }

    override fun sendEvent(event: NavigationEvent): Boolean {
        return send(event.name)
    }

    override fun isConnected(): Boolean {
        return _connectionState.value == SerialConnectionState.CONNECTED && serialPort != null
    }

    fun unregister() {
        try {
            context.unregisterReceiver(usbReceiver)
        } catch (_: Exception) {}
        disconnect()
    }
}
