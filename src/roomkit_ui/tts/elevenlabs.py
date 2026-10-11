"""ElevenLabs cloud TTS provider factory."""

from __future__ import annotations

from typing import Any

DEFAULT_MODEL = "eleven_v3"

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

    config = ElevenLabsConfig(
        api_key=api_key,
        voice_id=voice_id,
        model_id=model_id(settings),
        output_format="pcm_24000",
    )
    return ElevenLabsTTSProvider(config), 24000
