"""Google Gemini TTS provider factory."""

from __future__ import annotations

from typing import Any

# Built for voice agents: about 0.7 s to the first audio, against 1.1-1.6 s
# for 3.8 Flash, which has more acting range (roomkit, measured 2026-09-27).
DEFAULT_MODEL = "gemini-3.8-flash-lite-tts"
DEFAULT_VOICE = "Kore"


def create(settings: dict) -> tuple[Any, int]:
    """Create a Gemini TTS provider. Returns (provider, 24000).

    The Gemini key is the one Gemini Live and the LLM use.  No language is
    set: the model takes it from the text, so a reply in French is spoken in
    French whatever the STT language.
    """
    from roomkit.voice.tts.gemini import OUTPUT_SAMPLE_RATE, GeminiTTSConfig, GeminiTTSProvider

    api_key = str(settings.get("api_key", "") or "").strip()
    if not api_key:
        raise ValueError("Google API key is required for Gemini TTS. Open Settings to enter it.")
    config = GeminiTTSConfig(
        api_key=api_key,
        model=str(settings.get("gemini_tts_model", "") or "").strip() or DEFAULT_MODEL,
        voice=str(settings.get("gemini_tts_voice", "") or "").strip() or DEFAULT_VOICE,
        style_prompt=str(settings.get("gemini_tts_style", "") or "").strip() or None,
    )
    return GeminiTTSProvider(config), OUTPUT_SAMPLE_RATE
