"""
stt.py
------
Groq Speech-to-Text and voice destination input service (Phase 7).

Transcribes incoming voice commands using Groq Whisper STT (whisper-large-v3-turbo),
validates the wake phrase ("Hello Haptic Guide"), extracts the requested destination,
and forwards the destination directly into the existing Phase 3 destination search
and Phase 4 route calculation pipeline.

Security:
- GROQ_API_KEY is read strictly from environment variables.
- The API key is NEVER hardcoded, logged, or exposed over the API/network.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from navigation.routing import calculate_route_and_update_state
from navigation.search import search_destination_and_update_state
from navigation.state import GeoPoint, NavigationState, PlaceCandidate, RouteSnapshot

logger = logging.getLogger(__name__)

GROQ_WHISPER_MODEL: str = "whisper-large-v3-turbo"

# Wake phrase detection patterns (case-insensitive, handles spacing/punctuation variations)
_WAKE_PHRASE_PATTERNS: Sequence[re.Pattern] = (
    re.compile(r"^\s*(?:hey|hello|hi)?\s*haptic\s*guide[\s,!:.-]*", re.IGNORECASE),
    re.compile(r"^\s*(?:hey|hello|hi)?\s*hapticguide[\s,!:.-]*", re.IGNORECASE),
    re.compile(r"^\s*(?:hey|hello|hi)?\s*haptic-guide[\s,!:.-]*", re.IGNORECASE),
)

# Destination lead-in removal patterns
_COMMAND_PREFIX_PATTERNS: Sequence[re.Pattern] = (
    re.compile(r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:take\s+me\s+to|bring\s+me\s+to|lead\s+me\s+to)\s+(?:the\s+)?", re.IGNORECASE),
    re.compile(r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:navigate\s+to|directions\s+to|route\s+to|guide\s+me\s+to)\s+(?:the\s+)?", re.IGNORECASE),
    re.compile(r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:go\s+to|head\s+to|walk\s+to|drive\s+to)\s+(?:the\s+)?", re.IGNORECASE),
    re.compile(r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:find|search\s+for|look\s+for|locate)\s+(?:the\s+)?", re.IGNORECASE),
    re.compile(r"^(?:i\s+want\s+to\s+go\s+to|i\s+need\s+to\s+go\s+to|i\s+would\s+like\s+to\s+go\s+to)\s+(?:the\s+)?", re.IGNORECASE),
)

_TRAILING_CLEANUP_PATTERN = re.compile(r"[\s,!:.-]*(?:please|thanks|thank\s+you)?[\s,!:.-]*$", re.IGNORECASE)


class GroqSttError(Exception):
    """Base exception for Groq STT failures."""


class GroqAuthError(GroqSttError):
    """Raised when GROQ_API_KEY is missing or invalid."""


@dataclass(frozen=True)
class VoiceNavigationResult:
    """Outcome of processing a voice navigation command."""

    ok: bool
    transcript: str
    wake_phrase_detected: bool
    destination_query: Optional[str] = None
    candidate: Optional[PlaceCandidate] = None
    route: Optional[RouteSnapshot] = None
    error: Optional[str] = None


def detect_wake_phrase(transcript: str) -> Tuple[bool, str]:
    """
    Check if the transcript begins with the wake phrase 'Hello Haptic Guide'.
    Returns (detected, remaining_text).
    """
    if not isinstance(transcript, str):
        return False, ""
    text = transcript.strip()
    if not text:
        return False, ""

    for pat in _WAKE_PHRASE_PATTERNS:
        match = pat.match(text)
        if match:
            remnant = text[match.end() :].strip()
            # Strip leading commas or punctuation
            remnant = remnant.lstrip(",!?:.- \t")
            return True, remnant

    return False, ""


def extract_destination_query(command_text: str) -> str:
    """
    Extract destination name or query from the command text after wake phrase.

    Examples:
        "take me to the nearest KFC" -> "nearest KFC"
        "navigate to Central Park"   -> "Central Park"
        "find coffee shop near me"   -> "coffee shop near me"
        "nearest hospital, please"   -> "nearest hospital"
    """
    if not isinstance(command_text, str):
        return ""
    text = command_text.strip()
    if not text:
        return ""

    # Strip command prefix phrases
    for pat in _COMMAND_PREFIX_PATTERNS:
        match = pat.match(text)
        if match:
            text = text[match.end() :].strip()
            break

    # Strip trailing polite phrases or punctuation
    text = _TRAILING_CLEANUP_PATTERN.sub("", text).strip()
    return text


class GroqSttService:
    """
    Client wrapper for Groq Whisper transcription.
    Reads API key exclusively from GROQ_API_KEY environment variable.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[object] = None,
        model: str = GROQ_WHISPER_MODEL,
    ) -> None:
        self.model = model
        self._client = client
        self._api_key = api_key

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client

        key = self._api_key or os.environ.get("GROQ_API_KEY")
        if not key or not key.strip():
            raise GroqAuthError(
                "GROQ_API_KEY environment variable is not set. Please set GROQ_API_KEY to use voice STT."
            )

        try:
            from groq import Groq
            self._client = Groq(api_key=key.strip())
            return self._client
        except Exception as exc:
            raise GroqSttError(f"Failed to initialize Groq client: {exc}") from exc

    def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "command.m4a",
    ) -> str:
        """
        Transcribe raw audio bytes to text using Groq Whisper.
        """
        if not audio_bytes or len(audio_bytes) == 0:
            raise ValueError("Audio data is empty or missing.")

        client = self._get_client()
        try:
            # Send (filename, bytes) tuple to Groq audio transcription API
            response = client.audio.transcriptions.create(
                file=(filename, audio_bytes),
                model=self.model,
                response_format="json",
            )
            text = getattr(response, "text", "") or ""
            return text.strip()
        except Exception as exc:
            if "auth" in str(exc).lower() or "api_key" in str(exc).lower():
                raise GroqAuthError(f"Groq authentication error: {exc}") from exc
            raise GroqSttError(f"Groq transcription failed: {exc}") from exc


_DEFAULT_STT_SERVICE = GroqSttService()


def process_voice_destination(
    audio_bytes: bytes,
    state: NavigationState,
    filename: str = "command.m4a",
    origin: Optional[GeoPoint] = None,
    radius_m: Optional[int] = None,
    stt_service: Optional[GroqSttService] = None,
) -> VoiceNavigationResult:
    """
    End-to-end voice processing:
    1. Transcribe audio using Groq STT.
    2. Verify wake phrase.
    3. Extract destination query.
    4. Pass into existing Phase 3 Overpass search.
    5. Pass into existing Phase 4 OSRM route calculation.
    """
    service = stt_service or _DEFAULT_STT_SERVICE

    if not audio_bytes or len(audio_bytes) == 0:
        return VoiceNavigationResult(
            ok=False,
            transcript="",
            wake_phrase_detected=False,
            error="Audio data is empty or missing.",
        )

    # 1. Transcribe
    try:
        transcript = service.transcribe(audio_bytes, filename=filename)
    except GroqAuthError as exc:
        return VoiceNavigationResult(
            ok=False,
            transcript="",
            wake_phrase_detected=False,
            error=f"Groq API Key error: {exc}",
        )
    except Exception as exc:
        logger.error("STT transcription error: %s", exc)
        return VoiceNavigationResult(
            ok=False,
            transcript="",
            wake_phrase_detected=False,
            error=f"Speech transcription failed: {exc}",
        )

    if not transcript:
        return VoiceNavigationResult(
            ok=False,
            transcript="",
            wake_phrase_detected=False,
            error="No speech detected in audio recording.",
        )

    # 2. Wake phrase detection
    wake_detected, remnant = detect_wake_phrase(transcript)
    if not wake_detected:
        return VoiceNavigationResult(
            ok=False,
            transcript=transcript,
            wake_phrase_detected=False,
            error="Wake phrase 'Hello Haptic Guide' not detected in voice command.",
        )

    # 3. Extract destination query
    destination_query = extract_destination_query(remnant)
    if not destination_query:
        return VoiceNavigationResult(
            ok=False,
            transcript=transcript,
            wake_phrase_detected=True,
            destination_query="",
            error="Wake phrase recognized, but no destination was specified.",
        )

    # Resolve origin
    search_origin = origin
    if search_origin is None and state.current_location is not None:
        search_origin = GeoPoint(
            latitude=state.current_location.latitude,
            longitude=state.current_location.longitude,
        )

    if search_origin is None:
        return VoiceNavigationResult(
            ok=False,
            transcript=transcript,
            wake_phrase_detected=True,
            destination_query=destination_query,
            error="Current GPS location is required to search for nearby destinations.",
        )

    # 4. Search destination via existing Phase 3 Overpass search
    candidate = search_destination_and_update_state(
        state=state,
        query=destination_query,
        origin=search_origin,
        radius_m=radius_m,
    )

    if candidate is None:
        return VoiceNavigationResult(
            ok=False,
            transcript=transcript,
            wake_phrase_detected=True,
            destination_query=destination_query,
            error=state.error_message or f"No destination found for '{destination_query}'.",
        )

    # 5. Calculate route via existing Phase 4 OSRM routing
    route = calculate_route_and_update_state(
        state=state,
        origin=search_origin,
        destination=candidate.location,
    )

    return VoiceNavigationResult(
        ok=True,
        transcript=transcript,
        wake_phrase_detected=True,
        destination_query=destination_query,
        candidate=candidate,
        route=route,
    )
