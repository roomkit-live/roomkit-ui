"""Vui TTS provider factory (fluxions.ai): local, English, on an NVIDIA GPU.

Vui Nano generates each reply inside the conversation, the user's voice
included (the Voice Channel hands it the dialogue, ``engine_vc_helpers.tts_context``).
It speaks English only, so the session's prompt tells the model to answer in
English (:func:`prompt_note`).
"""

from __future__ import annotations

import os
from typing import Any

from roomkit_ui.tts._util import require_ref_audio

# roomkit's PRESET_VOICES (tests/test_tts_vui.py keeps the two equal), named
# here so the settings page lists them without importing the provider.
PRESETS = ("maeve", "abraham", "rhian", "harry")
# The voice of the clip in Conversation → Speak's Ref Audio and Ref Text, the
# fields Qwen3-TTS and NeuTTS clone from.
CLONE = "clone"
_DEFAULT_VOICE = "maeve"


def create(settings: dict) -> tuple[Any, int]:
    """Create a Vui TTS provider. Returns (provider, 24000)."""
    from roomkit.voice.tts.vui import SAMPLE_RATE, VuiTTSConfig, VuiTTSProvider, VuiVoice

    choice = _choice(settings)
    if choice == CLONE:
        ref_audio, ref_text = require_ref_audio(settings, "A cloned Vui voice")
        voice = VuiVoice(ref_audio=ref_audio, ref_text=ref_text)
    else:
        voice = VuiVoice(choice)
    return VuiTTSProvider(VuiTTSConfig(voices={choice: voice})), SAMPLE_RATE


def cache_fields(settings: dict) -> tuple:
    """The voice the provider is built with, so a change rebuilds the cached one.

    A cloned voice speaks with the clip it was built from: the file's
    modification time counts, so a clip replaced in place does too.
    """
    choice = _choice(settings)
    if choice != CLONE:
        return (choice,)
    ref_audio = settings.get("vc_tts_ref_audio", "")
    try:
        clip_mtime: int | None = os.stat(ref_audio).st_mtime_ns
    except OSError:
        clip_mtime = None
    return (choice, ref_audio, clip_mtime, settings.get("vc_tts_ref_text", ""))


def prompt_note(settings: dict) -> str:
    """Vui reads English only: a reply in another language comes out garbled."""
    return (
        "Your voice speaks English only. Always answer in English, whatever language "
        "the user speaks."
    )


def _choice(settings: dict) -> str:
    return (settings.get("vc_vui_voice", "") or "").strip() or _DEFAULT_VOICE
