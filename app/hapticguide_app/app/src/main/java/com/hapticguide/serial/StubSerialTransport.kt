package com.hapticguide.serial

import android.util.Log
import com.hapticguide.navigation.NavigationEvent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * In-memory / logging implementation of HapticSerialTransport.
 * Used for testing, previews, and graceful fallback when no physical USB device is attached.
 */
class StubSerialTransport : HapticSerialTransport {

    companion object {
        private const val TAG = "HapticSerialTransport"
    }

    private val _connectionState = MutableStateFlow(SerialConnectionState.CONNECTED)
    override val connectionState: StateFlow<SerialConnectionState> = _connectionState.asStateFlow()

    private val sentCommandHistory = mutableListOf<String>()

    override fun connect(): Boolean {
        _connectionState.value = SerialConnectionState.CONNECTED
        Log.i(TAG, "SERIAL CONNECTED (Stub)")
        return true
    }

    override fun disconnect() {
        _connectionState.value = SerialConnectionState.DISCONNECTED
        Log.i(TAG, "SERIAL DISCONNECTED (Stub)")
    }

    override fun send(command: String): Boolean {
        val cleanCmd = command.trim()
        if (cleanCmd.isEmpty()) return false

        val line = "$cleanCmd\n"
        synchronized(sentCommandHistory) {
            sentCommandHistory.add(cleanCmd)
        }
        Log.i(TAG, "SERIAL TX: $cleanCmd")
        return true
    }

    override fun sendEvent(event: NavigationEvent): Boolean {
        return send(event.name)
    }

    override fun isConnected(): Boolean {
        return _connectionState.value == SerialConnectionState.CONNECTED
    }

    fun getSentHistory(): List<String> {
        synchronized(sentCommandHistory) {
            return sentCommandHistory.toList()
        }
    }

    fun clearHistory() {
        synchronized(sentCommandHistory) {
            sentCommandHistory.clear()
        }
    }
}
