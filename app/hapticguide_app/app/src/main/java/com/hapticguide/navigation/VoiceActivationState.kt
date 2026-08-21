package com.hapticguide.navigation

/**
 * State machine for physical dual-button volume chord detection and voice recording.
 */
enum class VoiceActivationState(val statusText: String) {
    IDLE("Idle"),
    WAITING_FOR_PAIR("Waiting for second key..."),
    ARMED("Hold both buttons (1s)..."),
    RECORDING("Recording... Speak now"),
    STOPPING("Finalizing audio..."),
    READY_TO_UPLOAD("Ready to upload"),
    ERROR("Voice error");

    val isRecordingState: Boolean
        get() = this == RECORDING

    val isHolding: Boolean
        get() = this == ARMED || this == WAITING_FOR_PAIR
}
