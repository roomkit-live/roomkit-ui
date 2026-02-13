"""QSettings persistence for app configuration."""

from __future__ import annotations

import sys

from PySide6.QtCore import QSettings

_DEFAULT_HOTKEY = "<cmd_r>" if sys.platform == "darwin" else "<ctrl>+<shift>+h"

_DEFAULTS = {
    "provider": "gemini",
    "api_key": "",
    "openai_api_key": "",
    "model": "gemini-2.5-flash-native-audio-preview-12-2025",
    "openai_model": "gpt-4o-realtime-preview",
    "voice": "Aoede",
    "openai_voice": "alloy",
    "system_prompt": "You are a friendly voice assistant. Be concise and helpful.",
    "aec_mode": "webrtc",
    "denoise": "none",
    "input_device": None,
    "output_device": None,
    "stt_enabled": True,
    "stt_hotkey": _DEFAULT_HOTKEY,
    "stt_language": "",
    "stt_provider": "openai",
    "stt_model": "",
    "stt_translate": False,
    "inference_device": "cpu",
    "assistant_hotkey_enabled": True,
    "assistant_hotkey": "<ctrl>+<shift>+a",
    "theme": "dark",
    "mcp_servers": "[]",
    # Voice channel (STT → LLM → TTS) settings
    "conversation_mode": "realtime",  # "realtime" | "voice_channel"
    "vc_llm_provider": "anthropic",  # "anthropic" | "openai" | "gemini"
    "anthropic_api_key": "",
    "vc_anthropic_model": "claude-sonnet-4-20250514",
    "vc_openai_model": "gpt-4o",
    "vc_gemini_model": "gemini-2.0-flash",
    "vc_tts_provider": "piper",  # "piper" | "qwen3" | "neutts"
    "vc_tts_model": "",
    "vc_tts_ref_audio": "",  # Path to reference WAV for voice cloning
    "vc_tts_ref_text": "",  # Transcript of reference audio
    "vc_local_base_url": "http://localhost:11434/v1",
    "vc_local_model": "",
    "vc_local_api_key": "",
    "vc_local_tools": True,
    "vc_stt_model": "",
    "vc_vad_model": "",
    "vc_interruption": False,
}


def load_settings() -> dict:
    """Load persisted settings, falling back to defaults."""
    qs = QSettings()
    out: dict = {}
    for key, default in _DEFAULTS.items():
        val = qs.value(f"room/{key}", default)
        # QSettings returns strings for bools
        if isinstance(default, bool) and isinstance(val, str):
            val = val.lower() in ("true", "1", "yes")
        # Migrate denoise from bool (old) to string (new)
        if key == "denoise" and isinstance(val, bool):
            val = "rnnoise" if val else "none"
        elif key == "denoise" and isinstance(val, str) and val.lower() in ("true", "false"):
            val = "rnnoise" if val.lower() == "true" else "none"
        # QSettings returns strings for ints stored as device indices
        if key in ("input_device", "output_device"):
            if val is not None and val != "":
                try:
                    val = int(val)  # type: ignore[call-overload]
                except (TypeError, ValueError):
                    val = None
            else:
                val = None
        out[key] = val
    return out


def save_settings(settings: dict) -> None:
    """Persist settings to disk."""
    qs = QSettings()
    for key, val in settings.items():
        qs.setValue(f"room/{key}", val)
    qs.sync()
