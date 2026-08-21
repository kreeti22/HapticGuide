package com.hapticguide.navigation

/**
 * State machine for physical dual-button volume chord detection and automatic voice upload/navigation.
 *
 * Lifecycle:
 * IDLE
 *  ↓ (both volume buttons detected)
 * ARMED (1-second hold timer)
 *  ↓ (1-second hold satisfied + haptic pulse)
 * RECORDING
 *  ↓ (release)
 * STOPPING
 *  ↓
 * UPLOAD_PENDING
 *  ↓
 * UPLOADING
 *  ↓
 * SERVER_RESPONSE
 *  ↓
 * NAVIGATION (or ERROR)
 */
enum class VoiceActivationState(val statusText: String) {
    IDLE("Press Volume Up + Volume Down to navigate"),
    WAITING_FOR_PAIR("Waiting for second button..."),
    ARMED("Hold both buttons (1s)..."),
    RECORDING("Recording... Speak now"),
    STOPPING("Stopping..."),
    UPLOAD_PENDING("Upload pending..."),
    UPLOADING("Uploading audio..."),
    SERVER_RESPONSE("Processing..."),
    NAVIGATION("Navigation started"),
    ERROR("Error");

    val isRecordingState: Boolean
        get() = this == RECORDING

    val isProcessingState: Boolean
        get() = this == STOPPING || this == UPLOAD_PENDING || this == UPLOADING || this == SERVER_RESPONSE

    val isHolding: Boolean
        get() = this == ARMED || this == WAITING_FOR_PAIR
}
