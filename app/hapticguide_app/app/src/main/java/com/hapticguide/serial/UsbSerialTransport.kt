package com.hapticguide.serial

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.os.Build
import android.util.Log
import com.hapticguide.navigation.NavigationEvent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.IOException

/**
 * Concrete USB-OTG Serial Transport using Android's native UsbManager.
 *
 * Communicates with ESP32 USB-to-UART ICs (CP210x, CH340, FT232, PL2303, CDC ACM)
 * via USB bulk transfer at 115200 baud.
 *
 * Guarantees:
 * - Thread-safe transmission
 * - Never crashes the app if ESP32 is unplugged or disconnected
 * - Reconnect capability
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

    private var connection: UsbDeviceConnection? = null
    private var usbInterface: UsbInterface? = null
    private var endpointOut: UsbEndpoint? = null
    private var endpointIn: UsbEndpoint? = null
    private var currentDevice: UsbDevice? = null

    private val writeLock = Any()

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
                    if (granted && device != null) {
                        Log.i(TAG, "USB Permission granted for device: ${device.deviceName}")
                        openDevice(device)
                    } else {
                        Log.w(TAG, "USB Permission denied for device")
                        _connectionState.value = SerialConnectionState.ERROR
                    }
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
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(usbReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            context.registerReceiver(usbReceiver, filter)
        }
    }

    override fun connect(): Boolean {
        try {
            val deviceList = usbManager.deviceList
            if (deviceList.isEmpty()) {
                Log.d(TAG, "No USB devices connected")
                _connectionState.value = SerialConnectionState.DISCONNECTED
                return false
            }

            // Find first candidate device
            val device = deviceList.values.firstOrNull() ?: return false
            currentDevice = device

            if (!usbManager.hasPermission(device)) {
                _connectionState.value = SerialConnectionState.CONNECTING
                Log.i(TAG, "Requesting USB permission for ${device.deviceName} (VID: ${device.vendorId}, PID: ${device.productId})")
                val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0
                val permissionIntent = PendingIntent.getBroadcast(
                    context,
                    0,
                    Intent(ACTION_USB_PERMISSION),
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
            val conn = usbManager.openDevice(device)
            if (conn == null) {
                Log.e(TAG, "Failed to open USB device connection")
                _connectionState.value = SerialConnectionState.ERROR
                return false
            }

            // Locate interface with Bulk endpoints
            var targetInterface: UsbInterface? = null
            var outEp: UsbEndpoint? = null
            var inEp: UsbEndpoint? = null

            for (i in 0 until device.interfaceCount) {
                val iface = device.getInterface(i)
                for (j in 0 until iface.endpointCount) {
                    val ep = iface.getEndpoint(j)
                    if (ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK) {
                        if (ep.direction == UsbConstants.USB_DIR_OUT && outEp == null) {
                            outEp = ep
                            targetInterface = iface
                        } else if (ep.direction == UsbConstants.USB_DIR_IN && inEp == null) {
                            inEp = ep
                            targetInterface = iface
                        }
                    }
                }
                if (outEp != null) break
            }

            if (targetInterface == null || outEp == null) {
                Log.e(TAG, "No suitable USB Bulk endpoints found on device")
                conn.close()
                _connectionState.value = SerialConnectionState.ERROR
                return false
            }

            if (!conn.claimInterface(targetInterface, true)) {
                Log.e(TAG, "Failed to claim USB interface")
                conn.close()
                _connectionState.value = SerialConnectionState.ERROR
                return false
            }

            // Configure CDC-ACM / UART Line Coding: 115200 baud, 8 data bits, 1 stop bit, no parity
            try {
                val lineCoding = byteArrayOf(
                    (baudRate and 0xFF).toByte(),
                    ((baudRate shr 8) and 0xFF).toByte(),
                    ((baudRate shr 16) and 0xFF).toByte(),
                    ((baudRate shr 24) and 0xFF).toByte(),
                    0,    // 1 stop bit
                    0,    // Parity: None
                    8     // 8 Data bits
                )
                conn.controlTransfer(0x21, 0x20, 0, 0, lineCoding, lineCoding.size, 500)
                // Set DTR / RTS
                conn.controlTransfer(0x21, 0x22, 0x03, 0, null, 0, 500)
            } catch (e: Exception) {
                Log.d(TAG, "Line coding setup: ${e.message}")
            }

            synchronized(writeLock) {
                connection = conn
                usbInterface = targetInterface
                endpointOut = outEp
                endpointIn = inEp
            }

            _connectionState.value = SerialConnectionState.CONNECTED
            Log.i(TAG, "SERIAL CONNECTED: ${device.deviceName} (VID:${device.vendorId}, PID:${device.productId}) @ $baudRate baud")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Error configuring USB device: ${e.message}", e)
            _connectionState.value = SerialConnectionState.ERROR
            return false
        }
    }

    override fun disconnect() {
        synchronized(writeLock) {
            try {
                val conn = connection
                val iface = usbInterface
                if (conn != null && iface != null) {
                    conn.releaseInterface(iface)
                    conn.close()
                }
            } catch (e: Exception) {
                Log.w(TAG, "Error closing USB connection: ${e.message}")
            } finally {
                connection = null
                usbInterface = null
                endpointOut = null
                endpointIn = null
                _connectionState.value = SerialConnectionState.DISCONNECTED
                Log.i(TAG, "SERIAL DISCONNECTED")
            }
        }
    }

    override fun send(command: String): Boolean {
        val cleanCmd = command.trim()
        if (cleanCmd.isEmpty()) return false

        val payload = "$cleanCmd\n".toByteArray(Charsets.UTF_8)

        synchronized(writeLock) {
            val conn = connection
            val epOut = endpointOut

            if (conn == null || epOut == null) {
                Log.w(TAG, "Cannot send '$cleanCmd': USB Serial not connected")
                return false
            }

            try {
                val transferred = conn.bulkTransfer(epOut, payload, payload.size, TIMEOUT_MS)
                if (transferred >= 0) {
                    Log.i(TAG, "SERIAL TX: $cleanCmd")
                    return true
                } else {
                    Log.w(TAG, "SERIAL ERROR: bulkTransfer failed for command: $cleanCmd")
                    return false
                }
            } catch (e: Exception) {
                Log.e(TAG, "SERIAL ERROR writing to USB: ${e.message}", e)
                return false
            }
        }
    }

    override fun sendEvent(event: NavigationEvent): Boolean {
        return send(event.name)
    }

    override fun isConnected(): Boolean {
        return _connectionState.value == SerialConnectionState.CONNECTED
    }

    fun unregister() {
        try {
            context.unregisterReceiver(usbReceiver)
        } catch (_: Exception) {}
        disconnect()
    }
}
