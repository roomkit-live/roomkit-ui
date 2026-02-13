"""Qwen3-TTS provider factory."""

from __future__ import annotations

from typing import Any

from roomkit_ui.tts._util import require_ref_audio


def create(settings: dict) -> tuple[Any, int]:
    """Create a Qwen3-TTS provider from settings. Returns (provider, 24000)."""
    from roomkit.voice.tts.qwen3 import Qwen3TTSConfig, Qwen3TTSProvider, VoiceCloneConfig

    ref_audio, ref_text = require_ref_audio(settings, "Qwen3-TTS")
    tts = Qwen3TTSProvider(
        Qwen3TTSConfig(
            voices={
                "default": VoiceCloneConfig(
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                )
            },
        )
    )
    return tts, 24000
