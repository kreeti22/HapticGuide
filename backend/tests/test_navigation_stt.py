"""
test_navigation_stt.py
----------------------
Phase 7: Groq Speech-to-Text and voice destination input tests.

Verifies:
  - Wake phrase detection ("Hello Haptic Guide", "hello hapticguide", etc.)
  - Case-insensitivity and punctuation tolerance
  - Extraction of destination query ("take me to the nearest KFC" -> "nearest KFC")
  - Rejection when wake phrase is missing
  - Error handling when destination is empty
  - Error handling when GROQ_API_KEY is missing or invalid
  - Error handling when Groq API fails
  - Validation of audio data presence
  - End-to-end integration into Phase 3 search and Phase 4 route calculation
  - Obstacle detection protection (globals.latest_command untouched)
  - No real Groq API calls made during tests (fully mocked client).
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest

import globals
from navigation import session
from navigation.state import (
    GeoPoint,
    GpsFix,
    NavigationState,
    NavigationStatus,
    PlaceCandidate,
    RouteSnapshot,
    RouteStatus,
    RouteStep,
)
from navigation.stt import (
    GROQ_WHISPER_MODEL,
    GroqAuthError,
    GroqSttError,
    GroqSttService,
    VoiceNavigationResult,
    detect_wake_phrase,
    extract_destination_query,
    process_voice_destination,
)


# ---------------------------------------------------------------------------
# 1. Wake Phrase Detection Tests
# ---------------------------------------------------------------------------

def test_detect_wake_phrase_standard_variations():
    cases = [
        ("Hello Haptic Guide, take me to the nearest KFC.", True, "take me to the nearest KFC."),
        ("hello haptic guide take me to KFC", True, "take me to KFC"),
        ("HELLO HAPTIC GUIDE, find coffee shop", True, "find coffee shop"),
        ("Hey Haptic Guide! Navigate to Central Park", True, "Navigate to Central Park"),
        ("hi haptic guide, go to hospital", True, "go to hospital"),
        ("Hello HapticGuide, directions to hotel", True, "directions to hotel"),
        ("haptic guide, nearest pharmacy", True, "nearest pharmacy"),
        ("  hello  haptic   guide : take me home", True, "take me home"),
    ]

    for transcript, expected_detected, expected_remnant in cases:
        detected, remnant = detect_wake_phrase(transcript)
        assert detected is expected_detected, f"Failed detection for: {transcript}"
        assert remnant == expected_remnant, f"Failed remnant for: {transcript}"


def test_detect_wake_phrase_missing():
    invalid_cases = [
        "Take me to the nearest KFC",
        "Navigate to Central Park",
        "Hello Google, take me home",
        "Hey Siri, find coffee",
        "Where is the nearest hospital",
        "",
        "   ",
        None,
    ]

    for transcript in invalid_cases:
        detected, remnant = detect_wake_phrase(transcript)
        assert detected is False
        assert remnant == ""


def test_detect_wake_phrase_only_wake_phrase():
    detected, remnant = detect_wake_phrase("Hello Haptic Guide")
    assert detected is True
    assert remnant == ""

    detected2, remnant2 = detect_wake_phrase("Hello Haptic Guide!")
    assert detected2 is True
    assert remnant2 == ""


# ---------------------------------------------------------------------------
# 2. Destination Extraction Tests
# ---------------------------------------------------------------------------

def test_extract_destination_query_demo_command():
    # Demo command: "Hello Haptic Guide, take me to the nearest KFC."
    _, remnant = detect_wake_phrase("Hello Haptic Guide, take me to the nearest KFC.")
    destination = extract_destination_query(remnant)
    assert destination == "nearest KFC"


def test_extract_destination_query_patterns():
    test_cases = [
        ("take me to the nearest KFC.", "nearest KFC"),
        ("take me to KFC", "KFC"),
        ("can you please take me to the coffee shop", "coffee shop"),
        ("navigate to Central Park", "Central Park"),
        ("directions to Empire State Building", "Empire State Building"),
        ("go to the hospital, please", "hospital"),
        ("find coffee shop nearby", "coffee shop nearby"),
        ("search for nearest pharmacy", "nearest pharmacy"),
        ("i want to go to Times Square", "Times Square"),
        ("nearest KFC", "nearest KFC"),
        ("hospital", "hospital"),
    ]

    for remnant, expected_dest in test_cases:
        dest = extract_destination_query(remnant)
        assert dest == expected_dest, f"Failed extracting destination from '{remnant}' -> got '{dest}'"


def test_extract_destination_query_empty():
    assert extract_destination_query("") == ""
    assert extract_destination_query("   ") == ""
    assert extract_destination_query(None) == ""
    assert extract_destination_query("please") == ""


# ---------------------------------------------------------------------------
# 3. Groq STT Service & Authentication Tests
# ---------------------------------------------------------------------------

def test_missing_groq_api_key_raises_auth_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    service = GroqSttService(api_key=None)
    with pytest.raises(GroqAuthError) as exc_info:
        service.transcribe(b"dummy audio data")

    assert "GROQ_API_KEY environment variable is not set" in str(exc_info.value)


def test_empty_audio_bytes_raises_value_error():
    service = GroqSttService(api_key="mock-key")
    with pytest.raises(ValueError) as exc_info:
        service.transcribe(b"")

    assert "Audio data is empty" in str(exc_info.value)


def test_groq_stt_transcription_success():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Hello Haptic Guide, take me to the nearest KFC."
    mock_client.audio.transcriptions.create.return_value = mock_response

    service = GroqSttService(client=mock_client)
    transcript = service.transcribe(b"fake-audio-bytes", filename="audio.m4a")

    assert transcript == "Hello Haptic Guide, take me to the nearest KFC."
    mock_client.audio.transcriptions.create.assert_called_once_with(
        file=("audio.m4a", b"fake-audio-bytes"),
        model=GROQ_WHISPER_MODEL,
        temperature=0,
        response_format="verbose_json",
    )


def test_groq_stt_api_error_handling():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = RuntimeError("Network timeout connecting to Groq")

    service = GroqSttService(client=mock_client)
    with pytest.raises(GroqSttError) as exc_info:
        service.transcribe(b"fake-audio-bytes")

    assert "Groq transcription failed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. End-to-End Voice Navigation Integration Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def nav_state_with_gps():
    state = NavigationState()
    state.set_current_location(
        GpsFix(latitude=28.6139, longitude=77.2090, accuracy_m=5.0)
    )
    return state


def test_process_voice_destination_success(nav_state_with_gps):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Hello Haptic Guide, take me to the nearest KFC."
    mock_client.audio.transcriptions.create.return_value = mock_response

    stt_service = GroqSttService(client=mock_client)

    # Mock Overpass search response and OSRM routing response
    mock_candidate = PlaceCandidate(
        name="KFC Connaught Place",
        location=GeoPoint(latitude=28.6328, longitude=77.2197),
        distance_m=2300.0,
        osm_id=123456,
        osm_type="node",
    )

    with patch("navigation.stt.search_destination_and_update_state", return_value=mock_candidate) as mock_search, \
         patch("navigation.stt.calculate_route_and_update_state") as mock_route:

        result = process_voice_destination(
            audio_bytes=b"fake-audio-bytes",
            state=nav_state_with_gps,
            stt_service=stt_service,
        )

        assert result.ok is True
        assert result.transcript == "Hello Haptic Guide, take me to the nearest KFC."
        assert result.wake_phrase_detected is True
        assert result.destination_query == "nearest KFC"
        assert result.candidate == mock_candidate
        mock_search.assert_called_once()
        mock_route.assert_called_once()


def test_process_voice_destination_missing_wake_phrase(nav_state_with_gps):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Take me to the nearest KFC."
    mock_client.audio.transcriptions.create.return_value = mock_response

    stt_service = GroqSttService(client=mock_client)

    result = process_voice_destination(
        audio_bytes=b"fake-audio-bytes",
        state=nav_state_with_gps,
        stt_service=stt_service,
    )

    assert result.ok is False
    assert result.wake_phrase_detected is False
    assert "Wake phrase 'Hello Haptic Guide' not detected" in (result.error or "")


def test_process_voice_destination_empty_destination(nav_state_with_gps):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Hello Haptic Guide!"
    mock_client.audio.transcriptions.create.return_value = mock_response

    stt_service = GroqSttService(client=mock_client)

    result = process_voice_destination(
        audio_bytes=b"fake-audio-bytes",
        state=nav_state_with_gps,
        stt_service=stt_service,
    )

    assert result.ok is False
    assert result.wake_phrase_detected is True
    assert result.destination_query == ""
    assert "no destination was specified" in (result.error or "").lower()


def test_process_voice_destination_missing_gps():
    state = NavigationState()  # No GPS fix set
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Hello Haptic Guide, take me to KFC"
    mock_client.audio.transcriptions.create.return_value = mock_response

    stt_service = GroqSttService(client=mock_client)

    result = process_voice_destination(
        audio_bytes=b"fake-audio-bytes",
        state=state,
        stt_service=stt_service,
    )

    assert result.ok is False
    assert "GPS location is required" in (result.error or "")


def test_voice_processing_does_not_modify_obstacle_state(nav_state_with_gps):
    with globals.command_lock:
        orig = dict(globals.latest_command)
        globals.latest_command.update({"left": 180, "front": 0, "right": 220, "back": 0})
        before = dict(globals.latest_command)

    try:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello Haptic Guide, take me to KFC"
        mock_client.audio.transcriptions.create.return_value = mock_response
        stt_service = GroqSttService(client=mock_client)

        with patch("navigation.stt.search_destination_and_update_state", return_value=None):
            process_voice_destination(
                audio_bytes=b"fake-audio-bytes",
                state=nav_state_with_gps,
                stt_service=stt_service,
            )

        with globals.command_lock:
            after = dict(globals.latest_command)
    finally:
        with globals.command_lock:
            globals.latest_command.update(orig)

    assert after == before
    assert after["left"] == 180
    assert after["right"] == 220


def test_post_voice_endpoint_empty_body(nav_state_with_gps):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from navigation.routes import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    res = client.post("/nav/voice", content=b"")
    assert res.status_code == 400
    data = res.json()
    assert data["ok"] is False
    assert "No audio file" in data["error"]


def test_post_voice_endpoint_multipart_upload(nav_state_with_gps):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from navigation.routes import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with patch("navigation.stt.process_voice_destination") as mock_process:
        from navigation.stt import VoiceNavigationResult
        from navigation.state import PlaceCandidate
        mock_process.return_value = VoiceNavigationResult(
            ok=True,
            transcript="Hello Haptic Guide, take me to Connaught Place",
            wake_phrase_detected=True,
            destination_query="Connaught Place",
            candidate=PlaceCandidate(name="Connaught Place", location=GeoPoint(28.6139, 77.2090), distance_m=120.0),
        )

        # Upload as multipart/form-data with file parameter (M4A)
        res = client.post(
            "/nav/voice",
            files={"file": ("voice_command.m4a", b"fake-m4a-audio-data", "audio/mp4")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["transcript"] == "Hello Haptic Guide, take me to Connaught Place"
        assert data["destination"]["name"] == "Connaught Place"


def test_post_voice_endpoint_raw_binary_upload(nav_state_with_gps):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from navigation.routes import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with patch("navigation.stt.process_voice_destination") as mock_process:
        from navigation.stt import VoiceNavigationResult
        from navigation.state import PlaceCandidate
        mock_process.return_value = VoiceNavigationResult(
            ok=True,
            transcript="Hello Haptic Guide, navigate to Starbucks",
            wake_phrase_detected=True,
            destination_query="Starbucks",
            candidate=PlaceCandidate(name="Starbucks", location=GeoPoint(28.6130, 77.2085), distance_m=80.0),
        )

        # Upload as raw binary stream with Content-Type: audio/mp4 (Android NavHttpClient format)
        res = client.post(
            "/nav/voice",
            content=b"fake-binary-audio-bytes",
            headers={"Content-Type": "audio/mp4"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["transcript"] == "Hello Haptic Guide, navigate to Starbucks"
        assert data["destination"]["name"] == "Starbucks"

