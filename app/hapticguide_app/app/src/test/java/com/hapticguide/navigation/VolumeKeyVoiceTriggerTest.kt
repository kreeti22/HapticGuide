package com.hapticguide.navigation

import android.view.KeyEvent
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class VolumeKeyVoiceTriggerTest {

    private val testDispatcher = StandardTestDispatcher()
    private val testScope = TestScope(testDispatcher)

    private lateinit var voiceRecorderStub: VoiceRecorderStub
    private lateinit var phoneHapticPlayerStub: PhoneHapticPlayerStub
    private lateinit var trigger: VolumeKeyVoiceTrigger

    @Before
    fun setUp() {
        voiceRecorderStub = VoiceRecorderStub()
        phoneHapticPlayerStub = PhoneHapticPlayerStub()
        trigger = VolumeKeyVoiceTrigger(
            voiceRecorder = voiceRecorderStub,
            phoneHapticPlayer = phoneHapticPlayerStub,
            coroutineScope = testScope,
        )
    }

    @Test
    fun testSingleVolumeUpDoesNotTriggerRecordingImmediately() = testScope.runTest {
        val handled = trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_UP, 0)
        assertTrue(handled)
        assertTrue(trigger.isVolUpPressed)
        assertFalse(trigger.isVolDownPressed)

        assertEquals(VoiceActivationState.WAITING_FOR_PAIR, trigger.activationState.value)
        assertFalse(voiceRecorderStub.isRecordingStarted)

        // Advance past hold threshold - still should NOT record because only 1 key was pressed
        advanceTimeBy(1200)
        assertEquals(VoiceActivationState.IDLE, trigger.activationState.value)
        assertFalse(voiceRecorderStub.isRecordingStarted)
    }

    @Test
    fun testSingleVolumeDownDoesNotTriggerRecordingImmediately() = testScope.runTest {
        val handled = trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_DOWN, 0)
        assertTrue(handled)
        assertFalse(trigger.isVolUpPressed)
        assertTrue(trigger.isVolDownPressed)

        assertEquals(VoiceActivationState.WAITING_FOR_PAIR, trigger.activationState.value)
        assertFalse(voiceRecorderStub.isRecordingStarted)

        advanceTimeBy(1200)
        assertEquals(VoiceActivationState.IDLE, trigger.activationState.value)
        assertFalse(voiceRecorderStub.isRecordingStarted)
    }

    @Test
    fun testBothButtonsHeldForOneSecondTriggersRecording() = testScope.runTest {
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_UP, 0)
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_DOWN, 0)

        assertTrue(trigger.isVolUpPressed)
        assertTrue(trigger.isVolDownPressed)
        assertEquals(VoiceActivationState.ARMED, trigger.activationState.value)
        assertFalse(voiceRecorderStub.isRecordingStarted)

        // Advance 500ms (halfway) - should still be ARMED
        advanceTimeBy(500)
        assertEquals(VoiceActivationState.ARMED, trigger.activationState.value)
        assertFalse(voiceRecorderStub.isRecordingStarted)

        // Advance remaining 500ms to hit 1000ms threshold
        advanceTimeBy(501)
        assertEquals(VoiceActivationState.RECORDING, trigger.activationState.value)
        assertTrue(voiceRecorderStub.isRecordingStarted)
        assertTrue(phoneHapticPlayerStub.vibrationPlayed)

        // Release buttons
        trigger.handleKeyUp(KeyEvent.KEYCODE_VOLUME_UP)
        assertEquals(VoiceActivationState.READY_TO_UPLOAD, trigger.activationState.value)
        assertTrue(voiceRecorderStub.isRecordingStopped)
    }

    @Test
    fun testEarlyReleaseCancelsArmedStateWithoutRecording() = testScope.runTest {
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_UP, 0)
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_DOWN, 0)

        assertEquals(VoiceActivationState.ARMED, trigger.activationState.value)

        // Release after only 400ms (before 1000ms threshold)
        advanceTimeBy(400)
        trigger.handleKeyUp(KeyEvent.KEYCODE_VOLUME_UP)

        assertEquals(VoiceActivationState.IDLE, trigger.activationState.value)
        assertFalse(voiceRecorderStub.isRecordingStarted)

        // Advance past threshold
        advanceTimeBy(1000)
        assertEquals(VoiceActivationState.IDLE, trigger.activationState.value)
        assertFalse(voiceRecorderStub.isRecordingStarted)
    }

    @Test
    fun testAutoRepeatKeyEventsIgnoredDuringHold() = testScope.runTest {
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_UP, 0)
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_DOWN, 0)

        // Simulate Android hardware auto-repeating down events
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_UP, 1)
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_DOWN, 1)
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_UP, 2)

        advanceTimeBy(1001)
        assertEquals(VoiceActivationState.RECORDING, trigger.activationState.value)
        assertTrue(voiceRecorderStub.isRecordingStarted)
    }

    private class VoiceRecorderStub : VoiceRecorder(DummyContext()) {
        var isRecordingStarted = false
        var isRecordingStopped = false

        override fun startRecording(): Boolean {
            isRecordingStarted = true
            return true
        }

        override fun stopRecordingAndSend(onResult: ((org.json.JSONObject?) -> Unit)?) {
            isRecordingStopped = true
            onResult?.invoke(null)
        }
    }

    private class PhoneHapticPlayerStub : PhoneHapticPlayer(null) {
        var vibrationPlayed = false
        override fun playPattern(timings: LongArray) {
            vibrationPlayed = true
        }
    }

    private class DummyContext : android.content.ContextWrapper(null) {
        override fun getCacheDir(): java.io.File {
            val dir = java.io.File(System.getProperty("java.io.tmpdir"), "haptic_test_cache")
            dir.mkdirs()
            return dir
        }
    }
}
