"""Azure Speech TTS provider factory: MAI-Voice and Azure's neural voices."""

from __future__ import annotations

from typing import Any

from roomkit_ui.missing_key import MissingKeyError


def create(settings: dict) -> tuple[Any, int]:
    """Create an Azure Speech TTS provider. Returns (provider, 24000).

    The voice name picks the model: ``en-US-Harper:MAI-Voice-2.1-Flash``
    (roomkit's default) is MAI-Voice-2.1-Flash, ``fr-FR-Soleil:MAI-Voice-2.1-Flash``
    speaks French, a ``...Neural`` name is one of Azure's neural voices.
    """
    from roomkit.voice.tts.azure_speech import (
        DEFAULT_VOICE,
        AzureSpeechTTSConfig,
        AzureSpeechTTSProvider,
    )

    api_key = settings.get("azure_speech_api_key", "")
    region = (settings.get("azure_speech_region", "") or "").strip()
    if not api_key or not region:
        raise MissingKeyError(
            "Azure Speech TTS needs the resource's key and region (e.g. swedencentral). "
            "Open Settings to enter them."
        )
    config = AzureSpeechTTSConfig(
        api_key=api_key,
        region=region,
        voice=(settings.get("azure_tts_voice", "") or "").strip() or DEFAULT_VOICE,
        rate=(settings.get("azure_tts_rate", "") or "").strip() or None,
        sample_rate=24000,
    )
    return AzureSpeechTTSProvider(config), 24000
