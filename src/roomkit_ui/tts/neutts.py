"""NeuTTS provider factory."""

from __future__ import annotations

from typing import Any

from roomkit_ui.tts._util import require_ref_audio


def create(settings: dict) -> tuple[Any, int]:
    """Create a NeuTTS provider from settings. Returns (provider, 24000)."""
    from roomkit.voice.tts.neutts import NeuTTSConfig, NeuTTSProvider, NeuTTSVoiceConfig

    ref_audio, ref_text = require_ref_audio(settings, "NeuTTS")
    tts = NeuTTSProvider(
        NeuTTSConfig(
            voices={
                "default": NeuTTSVoiceConfig(
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                )
            },
        )
    )
    return tts, 24000
