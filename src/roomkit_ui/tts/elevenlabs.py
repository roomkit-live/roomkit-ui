"""ElevenLabs cloud TTS provider factory."""

from __future__ import annotations

from typing import Any


def create(settings: dict) -> tuple[Any, int]:
    """Create an ElevenLabs TTS provider. Returns (provider, sample_rate)."""
    from roomkit.voice.tts.elevenlabs import ElevenLabsConfig, ElevenLabsTTSProvider

    api_key = settings.get("elevenlabs_api_key", "")
    if not api_key:
        raise ValueError("ElevenLabs API key is required for ElevenLabs TTS.")
    voice_id = settings.get("elevenlabs_voice_id", "") or "21m00Tcm4TlvDq8ikWAM"
    model_id = settings.get("elevenlabs_model", "") or "eleven_v3"

    config = ElevenLabsConfig(
        api_key=api_key,
        voice_id=voice_id,
        model_id=model_id,
        output_format="pcm_24000",
    )
    return ElevenLabsTTSProvider(config), 24000
