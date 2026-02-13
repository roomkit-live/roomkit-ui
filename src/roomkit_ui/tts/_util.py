"""Shared helpers for TTS provider factories."""

from __future__ import annotations


def require_ref_audio(settings: dict, label: str) -> tuple[str, str]:
    """Extract and validate reference audio settings for voice-cloning TTS."""
    ref_audio = settings.get("vc_tts_ref_audio", "")
    ref_text = settings.get("vc_tts_ref_text", "")
    if not ref_audio or not ref_text:
        raise ValueError(f"{label} requires a reference WAV and its transcript in Settings.")
    return ref_audio, ref_text
