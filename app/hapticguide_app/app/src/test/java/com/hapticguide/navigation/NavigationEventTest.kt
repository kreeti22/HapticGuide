package com.hapticguide.navigation

import com.hapticguide.serial.SerialConnectionState
import com.hapticguide.serial.StubSerialTransport
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NavigationEventTest {

    @Test
    fun testNavigationEventEnumParsing() {
        assertEquals(NavigationEvent.START, NavigationEvent.fromEventString("NAVIGATION_START"))
        assertEquals(NavigationEvent.START, NavigationEvent.fromEventString("START"))
        assertEquals(NavigationEvent.LEFT, NavigationEvent.fromEventString("NAVIGATION_LEFT"))
        assertEquals(NavigationEvent.LEFT, NavigationEvent.fromEventString("left"))
        assertEquals(NavigationEvent.RIGHT, NavigationEvent.fromEventString("NAVIGATION_RIGHT"))
        assertEquals(NavigationEvent.FRONT, NavigationEvent.fromEventString("NAVIGATION_FRONT"))
        assertEquals(NavigationEvent.ARRIVAL, NavigationEvent.fromEventString("NAVIGATION_ARRIVAL"))

        assertNull(NavigationEvent.fromEventString(null))
        assertNull(NavigationEvent.fromEventString(""))
        assertNull(NavigationEvent.fromEventString("null"))
        assertNull(NavigationEvent.fromEventString("UNKNOWN_EVENT"))
    }

    @Test
    fun testNavigationDecisionJsonParsing() {
        val json = JSONObject().apply {
            put("status", "NAVIGATING")
            put("route_status", "ACTIVE")
            put("destination_name", "Central Park")
            put("current_instruction", "Turn left in 30 meters")
            put("next_instruction", "Continue straight")
            put("distance_to_next_m", 30.5)
            put("remaining_distance_m", 250.0)
            put("total_route_distance_m", 500.0)
            put("total_route_duration_s", 360.0)
            put("is_maneuver_imminent", true)
            put("is_off_route", false)
            put("is_arrived", false)
            put("pending_haptic_event", "NAVIGATION_LEFT")
            put("gps_health", "ACTIVE")
        }

        val decision = NavigationDecision.fromJsonObject(json)

        assertEquals("NAVIGATING", decision.status)
        assertEquals("ACTIVE", decision.routeStatus)
        assertEquals("Central Park", decision.destinationName)
        assertEquals("Turn left in 30 meters", decision.currentInstruction)
        assertEquals("Continue straight", decision.nextInstruction)
        assertEquals(30.5, decision.distanceToNextM ?: 0.0, 0.001)
        assertEquals(250.0, decision.remainingDistanceM ?: 0.0, 0.001)
        assertTrue(decision.isManeuverImminent)
        assertFalse(decision.isOffRoute)
        assertFalse(decision.isArrived)
        assertEquals(NavigationEvent.LEFT, decision.pendingHapticEvent)
        assertEquals("ACTIVE", decision.gpsHealth)
    }

    @Test
    fun testStubSerialTransportProtocol() {
        val transport = StubSerialTransport()
        assertTrue(transport.isConnected())
        assertEquals(SerialConnectionState.CONNECTED, transport.connectionState.value)

        assertTrue(transport.send("START"))
        assertTrue(transport.send("LEFT"))
        assertTrue(transport.send("RIGHT"))
        assertTrue(transport.send("FRONT"))
        assertTrue(transport.send("ARRIVAL"))
        assertTrue(transport.send("STOP"))

        val history = transport.getSentHistory()
        assertEquals(listOf("START", "LEFT", "RIGHT", "FRONT", "ARRIVAL", "STOP"), history)

        transport.disconnect()
        assertFalse(transport.isConnected())
        assertEquals(SerialConnectionState.DISCONNECTED, transport.connectionState.value)
    }

    @Test
    fun testExactEventToSerialMapping() {
        val transport = StubSerialTransport()
        val handler = NavigationEventHandler(
            phoneHapticPlayer = PhoneHapticPlayerStub(),
            serialTransport = transport
        )

        // Verify START -> "START"
        handler.handleEvent(NavigationEvent.START)
        // Verify LEFT -> "LEFT"
        handler.handleEvent(NavigationEvent.LEFT)
        // Verify RIGHT -> "RIGHT"
        handler.handleEvent(NavigationEvent.RIGHT)
        // Verify FRONT -> "FRONT"
        handler.handleEvent(NavigationEvent.FRONT)
        // Verify ARRIVAL -> "ARRIVAL"
        handler.handleEvent(NavigationEvent.ARRIVAL)

        assertEquals(
            listOf("START", "LEFT", "RIGHT", "FRONT", "ARRIVAL"),
            transport.getSentHistory()
        )
    }

    @Test
    fun testManeuverDeduplicationAcrossContinuousGpsUpdates() {
        val transport = StubSerialTransport()
        val handler = NavigationEventHandler(
            phoneHapticPlayer = PhoneHapticPlayerStub(),
            serialTransport = transport
        )

        val decision1 = NavigationDecision(
            status = "NAVIGATING",
            currentInstruction = "In 40 meters, turn right on Main St",
            nextInstruction = "Head straight",
            distanceToNextM = 40.0,
            pendingHapticEvent = NavigationEvent.RIGHT,
        )

        // Simulate 5 continuous GPS updates during the same maneuver
        for (i in 1..5) {
            handler.handleDecision(decision1.copy(distanceToNextM = 40.0 - i))
        }

        // Must only transmit "RIGHT" ONCE, not 5 times
        assertEquals(listOf("RIGHT"), transport.getSentHistory())

        // Next step transition occurs
        val decision2 = NavigationDecision(
            status = "NAVIGATING",
            currentInstruction = "Turn left onto Oak Ave",
            nextInstruction = "Destination is on left",
            distanceToNextM = 30.0,
            pendingHapticEvent = NavigationEvent.LEFT,
        )

        // Simulate 3 continuous GPS updates on new step
        for (i in 1..3) {
            handler.handleDecision(decision2.copy(distanceToNextM = 30.0 - i))
        }

        // Must now have exactly one "LEFT" added
        assertEquals(listOf("RIGHT", "LEFT"), transport.getSentHistory())

        // Reset navigation session
        handler.reset()
        assertEquals(listOf("RIGHT", "LEFT", "STOP"), transport.getSentHistory())
    }

    @Test
    fun testOncePerSessionStartEmissions() {
        val transport = StubSerialTransport()
        val handler = NavigationEventHandler(
            phoneHapticPlayer = PhoneHapticPlayerStub(),
            serialTransport = transport
        )

        val decisionStart = NavigationDecision(
            status = "NAVIGATING",
            currentInstruction = "Start walking north",
            nextInstruction = null,
            pendingHapticEvent = NavigationEvent.START,
        )

        // Multiple START decisions in same session
        handler.handleDecision(decisionStart)
        handler.handleDecision(decisionStart)
        handler.handleDecision(decisionStart)

        // Must emit only ONE START command
        assertEquals(listOf("START"), transport.getSentHistory())

        // Reset session
        handler.reset()
        assertEquals(listOf("START", "STOP"), transport.getSentHistory())

        // New session after reset can emit START again
        handler.handleDecision(decisionStart)
        assertEquals(listOf("START", "STOP", "START"), transport.getSentHistory())
    }

    @Test
    fun testDisconnectedSerialTransportDoesNotCrash() {
        val transport = StubSerialTransport()
        transport.disconnect()
        assertFalse(transport.isConnected())

        // Should return cleanly without throwing exceptions
        val handler = NavigationEventHandler(
            phoneHapticPlayer = PhoneHapticPlayerStub(),
            serialTransport = transport
        )

        handler.handleEvent(NavigationEvent.LEFT)
        handler.handleEvent(NavigationEvent.RIGHT)
        handler.reset()
    }

    private class PhoneHapticPlayerStub : PhoneHapticPlayer(null as android.content.Context?) {
        override fun handleHapticEvent(eventType: String?) {
            // No-op for unit test
        }
    }
}
