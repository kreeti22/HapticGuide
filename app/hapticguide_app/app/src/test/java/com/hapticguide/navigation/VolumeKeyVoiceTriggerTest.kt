package com.hapticguide.navigation

import android.view.KeyEvent
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

@OptIn(ExperimentalCoroutinesApi::class)
class VolumeKeyVoiceTriggerTest {

    private val testDispatcher = StandardTestDispatcher()
    private val testScope = TestScope(testDispatcher)

    private lateinit var voiceRecorderStub: VoiceRecorderStub
    private lateinit var phoneHapticPlayerStub: PhoneHapticPlayerStub
    private lateinit var trigger: VolumeKeyVoiceTrigger
    private var lastNavResult: JSONObject? = null

    @Before
    fun setUp() {
        lastNavResult = null
        voiceRecorderStub = VoiceRecorderStub()
        phoneHapticPlayerStub = PhoneHapticPlayerStub()
        trigger = VolumeKeyVoiceTrigger(
            voiceRecorder = voiceRecorderStub,
            phoneHapticPlayer = phoneHapticPlayerStub,
            coroutineScope = testScope,
            ioDispatcher = testDispatcher,
            onNavigationResult = { lastNavResult = it },
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
    }

    @Test
    fun testReleaseStopsRecordingAndAutomaticallyUploadsSuccessfully() = testScope.runTest {
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_UP, 0)
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_DOWN, 0)
        advanceTimeBy(1001)
        assertEquals(VoiceActivationState.RECORDING, trigger.activationState.value)

        // Configure stub response
        val mockResponse = JSONObject().apply {
            put("ok", true)
            put("transcript", "Hello Haptic Guide take me to Central Park")
            put("destination", JSONObject().put("name", "Central Park"))
        }
        voiceRecorderStub.customResponse = mockResponse

        // Release button -> triggers STOPPING and starts automatic upload pipeline
        trigger.handleKeyUp(KeyEvent.KEYCODE_VOLUME_UP)
        assertTrue(voiceRecorderStub.isRecordingStopped)

        // Advance coroutines for upload pipeline (UPLOAD_PENDING -> UPLOADING -> SERVER_RESPONSE -> NAVIGATION)
        advanceUntilIdle()

        assertEquals(VoiceActivationState.NAVIGATION, trigger.activationState.value)
        assertEquals("Central Park", trigger.lastDestination.value)
        assertEquals("Hello Haptic Guide take me to Central Park", trigger.lastTranscript.value)
        assertNotNull(lastNavResult)
        assertTrue(lastNavResult!!.optBoolean("ok"))
    }

    @Test
    fun testReleaseStopsRecordingAndHandlesServerError() = testScope.runTest {
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_UP, 0)
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_DOWN, 0)
        advanceTimeBy(1001)
        assertEquals(VoiceActivationState.RECORDING, trigger.activationState.value)

        val errorResponse = JSONObject().apply {
            put("ok", false)
            put("error", "No destination found")
        }
        voiceRecorderStub.customResponse = errorResponse

        trigger.handleKeyUp(KeyEvent.KEYCODE_VOLUME_UP)
        advanceUntilIdle()

        assertEquals(VoiceActivationState.ERROR, trigger.activationState.value)
        assertEquals("No destination found", trigger.statusDetail.value)
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

    @Test
    fun testEmptyAudioTriggersErrorState() = testScope.runTest {
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_UP, 0)
        trigger.handleKeyDown(KeyEvent.KEYCODE_VOLUME_DOWN, 0)
        advanceTimeBy(1001)
        assertEquals(VoiceActivationState.RECORDING, trigger.activationState.value)

        voiceRecorderStub.returnEmptyFile = true
        trigger.handleKeyUp(KeyEvent.KEYCODE_VOLUME_UP)

        assertEquals(VoiceActivationState.ERROR, trigger.activationState.value)
        assertEquals("No audio recorded", trigger.statusDetail.value)
    }

    @Test
    fun testManualRecordingStartAndToggleUpload() = testScope.runTest {
        assertEquals(VoiceActivationState.IDLE, trigger.activationState.value)

        // 1st toggle: starts recording manually
        trigger.toggleRecording()
        assertEquals(VoiceActivationState.RECORDING, trigger.activationState.value)
        assertTrue(voiceRecorderStub.isRecordingStarted)
        assertTrue(phoneHapticPlayerStub.vibrationPlayed)

        val mockResponse = JSONObject().apply {
            put("ok", true)
            put("transcript", "Hello Haptic Guide navigate to library")
            put("destination", JSONObject().put("name", "City Library"))
        }
        voiceRecorderStub.customResponse = mockResponse

        // 2nd toggle: stops recording and uploads
        trigger.toggleRecording()
        assertTrue(voiceRecorderStub.isRecordingStopped)

        advanceUntilIdle()
        assertEquals(VoiceActivationState.NAVIGATION, trigger.activationState.value)
        assertEquals("City Library", trigger.lastDestination.value)
        assertEquals("Hello Haptic Guide navigate to library", trigger.lastTranscript.value)
        assertNotNull(lastNavResult)
        assertTrue(lastNavResult!!.optBoolean("ok"))
    }

    private class VoiceRecorderStub : VoiceRecorder(DummyContext(), NavHttpClientStub()) {
        var isRecordingStarted = false
        var isRecordingStopped = false
        var returnEmptyFile = false
        var customResponse: JSONObject? = null

        override fun startRecording(): Boolean {
            isRecordingStarted = true
            isRecording = true
            return true
        }

        override fun stopRecording(): File? {
            isRecordingStopped = true
            isRecording = false
            if (returnEmptyFile) return null
            val file = File(DummyContext().cacheDir, AUDIO_FILENAME)
            file.writeBytes(byteArrayOf(1, 2, 3, 4))
            (httpClient as NavHttpClientStub).responseToReturn = customResponse
            return file
        }
    }

    private class NavHttpClientStub : NavHttpClient() {
        var responseToReturn: JSONObject? = null
        override fun postVoice(audioBytes: ByteArray, filename: String): JSONObject? {
            return responseToReturn
        }
    }

    private class PhoneHapticPlayerStub : PhoneHapticPlayer(null) {
        var vibrationPlayed = false
        override fun playPattern(timings: LongArray) {
            vibrationPlayed = true
        }
    }

    private class DummyContext : android.content.ContextWrapper(null) {
        override fun getCacheDir(): File {
            val dir = File(System.getProperty("java.io.tmpdir"), "haptic_test_cache")
            dir.mkdirs()
            return dir
        }
    }
}
