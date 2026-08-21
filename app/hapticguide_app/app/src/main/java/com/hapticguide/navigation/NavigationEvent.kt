package com.hapticguide.navigation

/**
 * Authoritative navigation haptic event definitions matching the backend contract.
 *
 * Contract:
 * - START:   3 pulses on belt-left, belt-right, and phone-front
 * - LEFT:    2 pulses on belt-left
 * - RIGHT:   2 pulses on belt-right
 * - FRONT:   2 pulses on phone-front
 * - ARRIVAL: Destination reached, navigation complete
 */
enum class NavigationEvent(val eventName: String) {
    START("NAVIGATION_START"),
    LEFT("NAVIGATION_LEFT"),
    RIGHT("NAVIGATION_RIGHT"),
    FRONT("NAVIGATION_FRONT"),
    ARRIVAL("NAVIGATION_ARRIVAL");

    companion object {
        fun fromEventString(raw: String?): NavigationEvent? {
            if (raw.isNullOrBlank() || raw.equals("null", ignoreCase = true)) return null
            val clean = raw.trim().uppercase()
            return entries.firstOrNull { it.name == clean || it.eventName == clean }
        }
    }
}
