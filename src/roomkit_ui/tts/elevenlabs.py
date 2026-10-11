"""ElevenLabs cloud TTS provider factory."""

from __future__ import annotations

from typing import Any

# v4: as expressive as v3 (audio tags) and, unlike v3, it streams — each
# sentence is spoken as soon as the model writes it.
DEFAULT_MODEL = "eleven_v4"

# The model families that read inline audio tags ([laughs], [whispers]) as
# delivery cues instead of words — roomkit's _AUDIO_TAG_MODELS.
_AUDIO_TAG_MODELS = ("eleven_v3", "eleven_v4")


def model_id(settings: dict) -> str:
    """The ElevenLabs model a session uses: the saved one, or the default."""
    return str(settings.get("elevenlabs_model", "") or DEFAULT_MODEL)


def reads_audio_tags(model: str) -> bool:
    """Whether *model* renders ``[laughs]``-style tags rather than reading them."""
    return model.startswith(_AUDIO_TAG_MODELS)


def create(settings: dict) -> tuple[Any, int]:
    """Create an ElevenLabs TTS provider. Returns (provider, sample_rate)."""
    from roomkit.voice.tts.elevenlabs import ElevenLabsConfig, ElevenLabsTTSProvider

    api_key = settings.get("elevenlabs_api_key", "")
    if not api_key:
        raise ValueError("ElevenLabs API key is required for ElevenLabs TTS.")
    voice_id = settings.get("elevenlabs_voice_id", "") or "21m00Tcm4TlvDq8ikWAM"

    # Streamed input: the reply is sent over a WebSocket sentence by sentence
    # as the LLM writes it, so the first one is heard ~140 ms after it is
    # written instead of once the whole reply is (2.6-3.9 s, roomkit's
    # measure).  v4 / v4 Turbo and the v2 / v2.5 models have a socket; v3 has
    # none and keeps whole-reply synthesis whatever the setting says.  The
    # socket stitches nothing across replies and, for v4, applies no voice
    # settings — none are customised here.
    config = ElevenLabsConfig(
        api_key=api_key,
        voice_id=voice_id,
        model_id=model_id(settings),
        output_format="pcm_24000",
        stream_input=bool(settings.get("elevenlabs_stream_input", True)),
    )
    return ElevenLabsTTSProvider(config), 24000
