"""Pocket TTS provider factory (Kyutai): local, CPU-friendly, clones a voice from a clip."""

from __future__ import annotations

import os
from typing import Any

# The models roomkit's PocketTTSConfig documents: one language per loaded
# model, each but English also as a larger "_24l" variant that sounds better
# and runs about three times slower (dutch needs pocket-tts 3.3+).
LANGUAGES = [
    ("Same as speech recognition", ""),
    ("English", "english"),
    ("French", "french"),
    ("French (larger, ~3× slower)", "french_24l"),
    ("German", "german"),
    ("German (larger, ~3× slower)", "german_24l"),
    ("Spanish", "spanish"),
    ("Spanish (larger, ~3× slower)", "spanish_24l"),
    ("Italian", "italian"),
    ("Italian (larger, ~3× slower)", "italian_24l"),
    ("Portuguese", "portuguese"),
    ("Portuguese (larger, ~3× slower)", "portuguese_24l"),
    ("Dutch", "dutch"),
    ("Dutch (larger, ~3× slower)", "dutch_24l"),
]

# Pre-made voices roomkit names: alba is PocketTTSConfig's default, estelle
# the French voice of its voice_local_pocket_fr example.
_DEFAULT_VOICE = "alba"
_DEFAULT_FRENCH_VOICE = "estelle"


def create(settings: dict) -> tuple[Any, int]:
    """Create a Pocket TTS provider. Returns (provider, 24000)."""
    from roomkit.voice.tts.pocket import SAMPLE_RATE, PocketTTSConfig, PocketTTSProvider

    language = _language(settings)
    config = PocketTTSConfig(
        language=language,
        voices={"default": _voice(settings, language)},
        device=_device(settings),
    )
    return PocketTTSProvider(config), SAMPLE_RATE


def cache_fields(settings: dict) -> tuple:
    """Everything the provider is built from, so a change rebuilds the cached one.

    A cloned voice speaks with the clip it was built from: the file's
    modification time counts, so a clip replaced in place does too.
    """
    language = _language(settings)
    voice = _voice(settings, language)
    try:
        clip_mtime: int | None = os.stat(voice).st_mtime_ns
    except OSError:
        clip_mtime = None  # a pre-made voice name, not a file
    return (language, voice, clip_mtime)


# The STT language codes (constants.STT_LANGUAGES) Pocket has a model for.
_STT_TO_POCKET = {
    "en": "english",
    "fr": "french",
    "de": "german",
    "es": "spanish",
    "it": "italian",
    "pt": "portuguese",
    "nl": "dutch",
}


def _language(settings: dict) -> str:
    """The chosen model, or by default the language speech recognition is set to.

    A language Pocket has no model for (or STT on auto-detect) speaks English.
    """
    chosen = (settings.get("vc_pocket_language", "") or "").strip()
    if chosen:
        return chosen
    return _STT_TO_POCKET.get((settings.get("stt_language", "") or "").strip(), "english")


def _voice(settings: dict, language: str) -> str:
    """A pre-made voice name or the path of a clip to clone."""
    voice = (settings.get("vc_pocket_voice", "") or "").strip()
    if voice:
        return os.path.expanduser(voice)
    return _DEFAULT_FRENCH_VOICE if language.startswith("french") else _DEFAULT_VOICE


def _device(settings: dict) -> str:
    """CUDA when the app's inference device is; Pocket TTS takes cpu or cuda only."""
    return "cuda" if settings.get("inference_device", "cpu") == "cuda" else "cpu"
