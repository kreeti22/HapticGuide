package com.hapticguide.camera

import android.content.Context
import android.content.SharedPreferences

/**
 * SettingsManager
 * ---------------
 * Persists the TCP server address and port across app restarts.
 * Backed by SharedPreferences — non-blocking apply() writes.
 */
class SettingsManager(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    companion object {
        private const val PREFS_NAME        = "hapticguide_prefs"
        private const val KEY_SERVER_IP     = "server_ip"
        private const val KEY_SERVER_PORT   = "server_port"
        private const val KEY_HTTP_PORT     = "http_port"
        private const val DEFAULT_SERVER_IP = "192.168.1.100"
        private const val DEFAULT_PORT      = 9000
        private const val DEFAULT_HTTP_PORT = 8000
    }

    fun getServerIp(): String =
        prefs.getString(KEY_SERVER_IP, DEFAULT_SERVER_IP) ?: DEFAULT_SERVER_IP

    fun setServerIp(ip: String) {
        prefs.edit().putString(KEY_SERVER_IP, ip.trim()).apply()
    }

    fun getServerPort(): Int =
        prefs.getInt(KEY_SERVER_PORT, DEFAULT_PORT)

    fun setServerPort(port: Int) {
        prefs.edit().putInt(KEY_SERVER_PORT, port).apply()
    }

    fun getHttpPort(): Int =
        prefs.getInt(KEY_HTTP_PORT, DEFAULT_HTTP_PORT)

    fun setHttpPort(port: Int) {
        prefs.edit().putInt(KEY_HTTP_PORT, port).apply()
    }
}
