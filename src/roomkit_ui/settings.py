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
    "vc_anthropic_model": "claude-sonnet-4-5-20250929",
    "vc_openai_model": "gpt-4o",
    "vc_gemini_model": "gemini-2.0-flash",
    "vc_stt_provider": "local",  # "local" | "gradium"
    "vc_tts_provider": "piper",  # "piper" | "qwen3" | "neutts" | "gradium"
    "vc_tts_model": "",
    "vc_tts_ref_audio": "",  # Path to reference WAV for voice cloning
    "vc_tts_ref_text": "",  # Transcript of reference audio
    "vc_local_base_url": "http://localhost:11434/v1",
    "vc_local_model": "",
    "vc_local_api_key": "",
    "vc_local_tools": True,
    "gradium_api_key": "",
    "gradium_region": "us",
    "vc_gradium_voice": "",  # Gradium TTS voice ID
    # Gradium advanced settings
    "gradium_language": "",  # STT/TTS language: en,fr,de,es,pt (empty = auto)
    "gradium_stt_model": "",  # STT model variant (empty = "default")
    "gradium_stt_delay": "",  # delay_in_frames: 7,8,10,12,14,16,20,24,36,48
    "gradium_stt_temperature": "",  # STT text temperature 0..1 (empty = 0)
    "gradium_vad_threshold": "",  # VAD turn threshold 0-1 (empty = 0.5)
    "gradium_vad_steps": "",  # Consecutive VAD steps (empty = 6)
    "gradium_tts_model": "",  # TTS model variant (empty = "default")
    "gradium_speed": "",  # padding_bonus: -4.0..4.0 (empty = default)
    "gradium_temperature": "",  # TTS temperature 0..1.4 (empty = 0.7)
    "gradium_cfg_coef": "",  # 1.0..4.0 (empty = 2.0)
    "gradium_rewrite_rules": "",  # "en","fr","de","es","pt" or custom rules
    "vc_stt_model": "",
    "vc_vad_model": "",
    "vc_interruption": False,
    # Agent Skills
    "skill_sources": "[]",  # JSON array of {type, url/path, label}
    "enabled_skills": "[]",  # JSON array of skill name strings
    "custom_attitudes": "[]",  # JSON array of {"name": str, "text": str}
    "selected_attitude": "",  # Name of active attitude (empty = none)
    # Gemini advanced settings
    "gemini_language": "",
    "gemini_no_interruption": False,
    "gemini_affective_dialog": False,
    "gemini_proactive_audio": False,
    "gemini_start_sensitivity": "",
    "gemini_end_sensitivity": "",
    "gemini_silence_duration_ms": "",
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
