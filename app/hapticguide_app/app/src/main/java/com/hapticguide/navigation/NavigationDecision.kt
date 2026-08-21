package com.hapticguide.navigation

import org.json.JSONObject

/**
 * Encapsulates a navigation state snapshot received dynamically from the backend.
 * Contains the authoritative route and maneuver decisions without duplicating logic in Kotlin.
 */
data class NavigationDecision(
    val status: String = "IDLE",
    val routeStatus: String = "NONE",
    val destinationName: String? = null,
    val currentInstruction: String? = null,
    val nextInstruction: String? = null,
    val distanceToNextM: Double? = null,
    val remainingDistanceM: Double? = null,
    val totalRouteDistanceM: Double? = null,
    val totalRouteDurationS: Double? = null,
    val isManeuverImminent: Boolean = false,
    val isOffRoute: Boolean = false,
    val isArrived: Boolean = false,
    val pendingHapticEvent: NavigationEvent? = null,
    val gpsHealth: String = "NONE",
    val gpsDetail: String? = null,
) {
    companion object {
        fun fromJsonObject(json: JSONObject?): NavigationDecision {
            if (json == null) return NavigationDecision()

            val progressObj = json.optJSONObject("progress")
            val rawEvent = json.optString("pending_haptic_event", null)
                ?: progressObj?.optString("pending_haptic_event", null)

            val event = NavigationEvent.fromEventString(rawEvent)

            val currInst = json.optString("current_instruction", null)
                ?: progressObj?.optJSONObject("current_instruction")?.optString("text", null)
            val nextInst = json.optString("next_instruction", null)
                ?: progressObj?.optJSONObject("next_instruction")?.optString("text", null)

            val distToNext = if (json.has("distance_to_next_m") && !json.isNull("distance_to_next_m")) {
                json.optDouble("distance_to_next_m")
            } else if (progressObj != null && progressObj.has("distance_to_next_m") && !progressObj.isNull("distance_to_next_m")) {
                progressObj.optDouble("distance_to_next_m")
            } else null

            val remainingDist = if (json.has("remaining_distance_m") && !json.isNull("remaining_distance_m")) {
                json.optDouble("remaining_distance_m")
            } else if (progressObj != null && progressObj.has("remaining_distance_m") && !progressObj.isNull("remaining_distance_m")) {
                progressObj.optDouble("remaining_distance_m")
            } else null

            val totalDist = if (json.has("total_route_distance_m") && !json.isNull("total_route_distance_m")) {
                json.optDouble("total_route_distance_m")
            } else null

            val totalDur = if (json.has("total_route_duration_s") && !json.isNull("total_route_duration_s")) {
                json.optDouble("total_route_duration_s")
            } else null

            return NavigationDecision(
                status = json.optString("status", progressObj?.optString("status", "IDLE")),
                routeStatus = json.optString("route_status", "NONE"),
                destinationName = json.optString("destination_name", null),
                currentInstruction = currInst,
                nextInstruction = nextInst,
                distanceToNextM = distToNext,
                remainingDistanceM = remainingDist,
                totalRouteDistanceM = totalDist,
                totalRouteDurationS = totalDur,
                isManeuverImminent = json.optBoolean("is_maneuver_imminent", progressObj?.optBoolean("is_maneuver_imminent", false) ?: false),
                isOffRoute = json.optBoolean("is_off_route", progressObj?.optBoolean("is_off_route", false) ?: false),
                isArrived = json.optBoolean("is_arrived", progressObj?.optBoolean("is_arrived", false) ?: false),
                pendingHapticEvent = event,
                gpsHealth = json.optString("gps_health", "NONE"),
                gpsDetail = json.optString("gps_detail", null),
            )
        }
    }
}
