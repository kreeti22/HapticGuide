package com.hapticguide.camera

import android.content.Context
import android.content.SharedPreferences

/**
 * SettingsManager encapsulates access to SharedPreferences for saving and retrieving
 * application configurations, primarily the local server IP address.
 */
class SettingsManager(context: Context) {

    private val sharedPreferences: SharedPreferences = context.getSharedPreferences(
        PREFS_NAME,
        Context.MODE_PRIVATE
    )

    companion object {
        private const val PREFS_NAME = "camera_streamer_prefs"
        private const val KEY_SERVER_IP = "server_ip"
        private const val DEFAULT_SERVER_IP = "192.168.1.100:8000/receive"
    }

    /**
     * Gets the currently saved server IP. Defaults to "192.168.1.100".
     */
    fun getServerIp(): String {
        return sharedPreferences.getString(KEY_SERVER_IP, DEFAULT_SERVER_IP) ?: DEFAULT_SERVER_IP
    }

    /**
     * Saves the server IP address to SharedPreferences.
     */
    fun setServerIp(ip: String) {
        sharedPreferences.edit().putString(KEY_SERVER_IP, ip.trim()).apply()
    }
}
