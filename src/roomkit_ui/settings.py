"""QSettings persistence for app configuration."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSettings

from roomkit_ui.secret_store import get_secret_store
from roomkit_ui.settings_secrets import (
    hydrate_cli_tool_secrets,
    hydrate_mcp_server_secrets,
    load_secret_setting,
    sanitize_cli_tools,
    sanitize_mcp_servers,
    save_secret_setting,
)

_DEFAULT_HOTKEY = "<cmd_r>" if sys.platform == "darwin" else "<ctrl>+<shift>+h"

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "openai_api_key",
        "anthropic_api_key",
        "elevenlabs_api_key",
        "vc_local_api_key",
        "deepgram_api_key",
        "gradium_api_key",
        "xai_api_key",
        "azure_speech_api_key",
    }
)


_DEFAULTS = {
    "provider": "gemini",
    "api_key": "",
    "openai_api_key": "",
    "model": "gemini-2.5-flash-native-audio-preview-12-2025",
    "openai_model": "gpt-realtime-2.1",
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
    # Auto-hangup: a session nobody is using keeps the provider billed and
    # the mic live.  Off by default — a session started by hand shouldn't
    # close on its own unless the user asked for it.
    "idle_hangup_enabled": False,
    "idle_hangup_seconds": 15,
    # Wake word. The phrase itself is not here — it is a voice fingerprint on
    # disk, not a string; this only records whether to listen and how eagerly.
    "wakeword_enabled": False,
    "wakeword_sensitivity": "balanced",  # cautious | balanced | responsive
    "telemetry_provider": "none",  # "none" | "console" | "otlp"
    "otlp_endpoint": "",  # OTLP gRPC endpoint (e.g. http://localhost:4317)
    "otlp_protocol": "grpc",  # "grpc" | "http"
    "otlp_service_name": "roomkit-ui",
    # Audio debug & recording
    "debug_taps_enabled": False,
    "debug_taps_stages": "all",  # "all" or comma-separated: "raw,post_denoiser,..."
    "debug_output_dir": "",  # empty = <data dir>/debug_audio (see paths.py)
    "recording_enabled": False,
    "recording_mode": "both",  # "inbound_only" | "outbound_only" | "both"
    "recording_channels": "stereo",  # "mixed" | "separate" | "stereo"
    "recording_output_dir": "",  # empty = <data dir>/recordings (see paths.py)
    "theme": "dark",
    "mcp_servers": "[]",
    # JSON array of {enabled, name, command, description, seed_help, help_depth, timeout}
    "cli_tools": "[]",
    # Voice channel (STT → LLM → TTS) settings
    "conversation_mode": "realtime",  # "realtime" | "voice_channel"
    "vc_llm_provider": "anthropic",  # "anthropic" | "openai" | "gemini"
    "anthropic_api_key": "",
    "vc_anthropic_model": "claude-sonnet-5-5",
    "vc_openai_model": "gpt-4o",
    "vc_gemini_model": "gemini-3.8-flash",
    "vc_stt_provider": "local",  # "local" | "gradium"
    "vc_tts_provider": "piper",  # "piper" | "qwen3" | "neutts" | "gradium" | "elevenlabs"
    "elevenlabs_api_key": "",
    "elevenlabs_voice_id": "",  # Empty = Rachel default (21m00Tcm4TlvDq8ikWAM)
    "elevenlabs_model": "",  # Empty = eleven_v4
    "vc_tts_model": "",
    "vc_tts_ref_audio": "",  # Path to reference WAV for voice cloning
    "vc_tts_ref_text": "",  # Transcript of reference audio
    "vc_local_base_url": "http://localhost:11434/v1",
    "vc_local_model": "",
    "vc_local_api_key": "",
    "vc_local_tools": True,
    "deepgram_api_key": "",
    "deepgram_model": "nova-3",
    "gradium_api_key": "",
    "gradium_region": "us",
    "vc_gradium_voice": "",  # Gradium TTS voice ID
    # Gradium advanced settings
    "gradium_language": "",  # STT/TTS language: en,fr,de,es,pt (empty = auto)
    "gradium_stt_model": "",  # STT model variant (empty = "default")
    "gradium_stt_delay": "",  # delay_in_frames: 7,8,10,12,14,16,20,24,36,48
    "gradium_stt_temperature": "",  # STT text temperature 0..1 (empty = 0)
    "gradium_vad_threshold": "",  # VAD inactivity_prob threshold 0-1 (empty = 0.9)
    "gradium_vad_steps": "",  # Consecutive steps above threshold (empty = 10, ×80ms)
    "gradium_tts_model": "",  # TTS model variant (empty = "default")
    "gradium_speed": "",  # padding_bonus: -4.0..4.0 (empty = default)
    "gradium_temperature": "",  # TTS temperature 0..1.4 (empty = 0.7)
    "gradium_cfg_coef": "",  # 1.0..4.0 (empty = 2.0)
    "gradium_rewrite_rules": "",  # "en","fr","de","es","pt" or custom rules
    "vc_stt_model": "",
    "vc_vad_model": "",
    "vad_threshold": "",  # 0.0–1.0 (empty = 0.35)
    "vad_silence_ms": "",  # ms of silence before SPEECH_END (empty = 500)
    "vad_min_speech_ms": "",  # minimum utterance length in ms (empty = 250)
    "vad_speech_pad_ms": "",  # pre-roll buffer in ms (empty = 1000, roomkit 0.90+)
    "vad_energy_silence_rms": "",  # energy fast-exit RMS threshold (empty = 20, 0 = off)
    "vc_turn_detector": "",  # "" (none) or "smart-turn"
    "vc_turn_threshold": "",  # 0.0–1.0 (empty = 0.5)
    # Speaker diarization
    "diarization_enabled": False,
    "diarization_model": "",
    "diarization_threshold": 0.4,
    "primary_speaker_mode": False,
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
    # OpenAI advanced settings
    "openai_turn_detection": "server_vad",  # "server_vad" | "semantic_vad" | "none"
    "openai_eagerness": "",  # 0.0–1.0, semantic_vad only (empty = default)
    "openai_vad_threshold": "",  # 0.0–1.0, server_vad only (empty = default)
    "openai_silence_duration_ms": "",  # server_vad only (empty = default)
    "openai_prefix_padding_ms": "",  # server_vad only (empty = default)
    "openai_interrupt_response": True,  # Allow interrupting AI response
    "openai_create_response": True,  # Auto-generate response on turn end
    "openai_reasoning_effort": "",  # ""|minimal|low|medium|high|xhigh (gpt-realtime-2+)
    "openai_voice_speed": "",  # 0.25–1.5 (empty = 1.0) — audio.output.speed
    "conversation_memory": True,  # persist conversations (SQLite) across sessions
    # Deepgram Voice Agent (realtime speech-to-speech; distinct from VC STT keys)
    "deepgram_agent_voice": "aura-2-thalia-en",  # Aura speak model
    "deepgram_agent_think_provider": "open_ai",  # "open_ai" | "anthropic" | "google"
    "deepgram_agent_think_model": "",  # empty = Deepgram default (gpt-4o-mini)
    "deepgram_agent_listen_model": "",  # empty = auto (nova-3; nova-2 for languages)
    "deepgram_agent_listen_language": "",  # e.g. "fr", "multi" (empty = English)
    "deepgram_agent_speak_provider": "",  # "" (Aura) | "eleven_labs" | "open_ai"
    "deepgram_agent_speak_model": "",  # vendor TTS model (empty = vendor default)
    "deepgram_agent_speak_voice": "",  # ElevenLabs voice ID / OpenAI voice name
    "deepgram_agent_speak_speed": "",  # 0.7–1.5, Aura voices (empty = 1.0)
    "deepgram_agent_greeting": "",  # optional line spoken at session open
    # Deepgram owns turn detection with no sensitivity knob.  The default
    # wiring mirrors roomkit's deepgram example (transport-level AEC +
    # webrtc NS + larger prebuffer), which keeps the mic open; half-duplex
    # (mic muted while the agent speaks) is the escape hatch for setups
    # whose echo still trips it.
    "deepgram_agent_half_duplex": False,
    # ElevenLabs Conversational AI (realtime)
    "elevenlabs_agent_id": "",  # required — agent from the ElevenLabs dashboard
    # xAI Grok realtime
    "xai_api_key": "",
    "xai_model": "grok-2-audio",
    "xai_voice": "eve",  # eve | ara | rex | sal | leo
    # xAI advanced (server-VAD tuning, wire-compatible with OpenAI's)
    "xai_vad_threshold": "",  # 0.0–1.0 (empty = default)
    "xai_silence_duration_ms": "",  # empty = default
    "xai_prefix_padding_ms": "",  # empty = default
    # Gemini 3.8 Live (roomkit 0.79+).  Sent only to the models that take them.
    "gemini_thinking_level": "",  # "" (roomkit sends LOW) | LOW | MEDIUM | HIGH
    "gemini_language_auto": False,  # user transcript may switch language mid-call
    "gemini_language_hints": "",  # comma-separated BCP-47 codes, e.g. "fr-FR, en-US"
    "gemini_custom_vocabulary": "",  # comma-separated names/terms for the user transcript
    # llama.cpp local LLM (roomkit 0.90+): roomkit downloads llama-server + model
    "vc_llamacpp_model": "",  # "repo:quant" or a .gguf path (empty = Qwen3-4B Q4_K_M)
    "vc_llamacpp_context": "",  # context window in tokens (empty = 8192)
    # Pocket TTS (roomkit 0.90+, Kyutai): one language per model, voice by name or clip
    # "" = the STT language's model (English when Pocket has none) | english | french_24l…
    "vc_pocket_language": "",
    "vc_pocket_voice": "",  # pre-made voice or a clip to clone (empty = alba / estelle)
    # Azure / Microsoft Foundry speech (roomkit 0.96, public preview): one resource,
    # one key for MAI-Transcribe (endpoint) and Azure Speech TTS (region)
    "azure_speech_api_key": "",  # secret — keyring, never QSettings
    "azure_mai_endpoint": "",  # https://<resource>.services.ai.azure.com
    "azure_mai_deployment": "",  # empty = MAI-Transcribe-2-Streaming
    "azure_speech_region": "",  # e.g. swedencentral
    "azure_tts_voice": "",  # empty = en-US-Harper:MAI-Voice-2.1-Flash
    "azure_tts_rate": "",  # SSML prosody rate: +15%, 1.2, fast (empty = the voice's own)
    # OpenAI GPT-Live (roomkit 0.70+, full-duplex): the live model talks, a backend
    # model OpenAI hosts reasons and calls the tools
    "openai_live_model": "gpt-live-1",
    "openai_live_voice": "marin",
    "openai_live_backend_model": "gpt-5.6-terra",  # roomkit's example backend
    "openai_live_backend_effort": "low",  # low | medium | high
    # Voice Channel pipeline (roomkit 0.96)
    # Barge-in: "off" | "immediate" | "semantic" (words only). Was the bool
    # "vc_interruption" (True = immediate), migrated by load_settings().
    "vc_interruption_mode": "off",
    # Send the reply to ElevenLabs as it is written (WebSocket; not on v3)
    "elevenlabs_stream_input": True,
    # Local (vLLM / Ollama) model reasoning: off by default, a voice reply
    # must not wait for seconds of hidden thinking
    "vc_local_thinking": False,
    # How long a turn Smart Turn judged unfinished waits for more speech
    "vc_turn_incomplete_wait_ms": "",  # ms (empty = 1500)
}

# Keys renamed since a release shipped: new key → (old key, old value → new value).
_RENAMED_KEYS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "vc_interruption_mode": (
        "vc_interruption",
        lambda old: "immediate" if str(old).lower() in ("true", "1", "yes") else "off",
    ),
}


# Defaults that moved on — retired by the vendor, or replaced by a better
# one: (old default, its successor, the notice).  The Settings dialog saves
# every field on close, so a stored value equal to an old default is, almost
# always, that default and not a deliberate pick.  It moves on with the
# default, and the chat says so once — a pick that happens to match can be
# made again.  Dates from roomkit 0.96.1's Anthropic catalog: Sonnet 4.5
# deprecated 2026-09-30, retiring 2026-11-30.
_RETIRED_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "vc_anthropic_model": (
        "claude-sonnet-4-5-20250929",
        "claude-sonnet-5-5",
        "Claude Sonnet 4.5 retires on 2026-11-30: the voice channel now uses "
        "Claude Sonnet 5.5. Pick another model in Settings → AI Provider → LLM.",
    ),
    # Absent from roomkit 0.96.1's Gemini catalog, which only drops ids the
    # vendor shut down (it still lists the deprecated 2.5 Flash-Lite).
    "vc_gemini_model": (
        "gemini-2.0-flash",
        "gemini-3.8-flash",
        "Gemini 2.0 Flash is no longer offered: the voice channel now uses "
        "Gemini 3.8 Flash. Pick another model in Settings → AI Provider → LLM.",
    ),
    # v3 has no streaming socket: v4 speaks as the reply is written.
    "elevenlabs_model": (
        "eleven_v3",
        "eleven_v4",
        "ElevenLabs now uses v4, which starts speaking while the reply is written. "
        "v3 is still in Settings → AI Provider → TTS.",
    ),
}
_NOTICES_GROUP = "notices"


def _migrate_retired_default(qs: QSettings, key: str) -> None:
    """Move a stored retired default to its successor and queue the notice."""
    retired = _RETIRED_DEFAULTS.get(key)
    if retired is None:
        return
    old, new, notice = retired
    if qs.value(f"room/{key}") != old:
        return
    qs.setValue(f"room/{key}", new)
    qs.setValue(f"{_NOTICES_GROUP}/{key}", notice)
    qs.sync()


def take_model_notices() -> list[str]:
    """The notices left by retired-default migrations, each returned once."""
    qs = QSettings()
    qs.beginGroup(_NOTICES_GROUP)
    notices = [str(qs.value(name)) for name in qs.childKeys()]
    qs.remove("")
    qs.endGroup()
    qs.sync()
    return notices


def _migrate_renamed_keys(qs: QSettings) -> None:
    """Move a value saved under a key's old name to its new one, converted.

    Done once: the old key is removed, and a value already saved under the
    new name wins over the old one.
    """
    for key, (old_key, convert) in _RENAMED_KEYS.items():
        if not qs.contains(f"room/{old_key}"):
            continue
        if not qs.contains(f"room/{key}"):
            qs.setValue(f"room/{key}", convert(qs.value(f"room/{old_key}")))
        qs.remove(f"room/{old_key}")
        qs.sync()


def _coerce_loaded(key: str, default: Any, val: Any) -> Any:
    """Turn what QSettings stored back into the type the default has."""
    # QSettings returns strings for bools
    if isinstance(default, bool) and isinstance(val, str):
        val = val.lower() in ("true", "1", "yes")
    # Migrate denoise from bool (old) to string (new)
    if key == "denoise" and isinstance(val, bool):
        val = "rnnoise" if val else "none"
    elif key == "denoise" and isinstance(val, str) and val.lower() in ("true", "false"):
        val = "rnnoise" if val.lower() == "true" else "none"
    # QSettings returns strings for floats
    if key == "diarization_threshold" and isinstance(val, str):
        try:
            val = float(val)
        except (ValueError, TypeError):
            val = 0.4
    # QSettings returns strings for ints stored as device indices
    if key in ("input_device", "output_device"):
        if val is not None and val != "":
            try:
                val = int(val)  # type: ignore[call-overload]
            except (TypeError, ValueError):
                val = None
        else:
            val = None
    return val


def load_settings() -> dict:
    """Load persisted settings, falling back to defaults."""
    qs = QSettings()
    store = get_secret_store()
    _migrate_renamed_keys(qs)
    out: dict = {}
    for key, default in _DEFAULTS.items():
        if key in _SECRET_KEYS:
            out[key] = load_secret_setting(qs, store, key)
            continue

        _migrate_retired_default(qs, key)
        val = qs.value(f"room/{key}", default)
        if key == "mcp_servers":
            val = hydrate_mcp_server_secrets(val, qs, store)
        elif key == "cli_tools":
            val = hydrate_cli_tool_secrets(val, qs, store)
        val = _coerce_loaded(key, default, val)
        out[key] = val
    return out


def load_setting(key: str) -> Any:
    """One persisted, non-secret setting — without reading the keyring.

    For code that must update a single value outside the Settings dialog;
    a secret lives in the keyring and is only read by load_settings().
    """
    if key in _SECRET_KEYS:
        raise ValueError(f"{key} is a secret: read it with load_settings()")
    return QSettings().value(f"room/{key}", _DEFAULTS[key])


def save_settings(settings: dict) -> None:
    """Persist settings to disk."""
    qs = QSettings()
    store = get_secret_store()
    for key, val in settings.items():
        if key in _SECRET_KEYS:
            save_secret_setting(qs, store, key, val)
            continue
        if key == "mcp_servers":
            val = sanitize_mcp_servers(val, store, persist=True)
        elif key == "cli_tools":
            val = sanitize_cli_tools(val, store, persist=True)
        qs.setValue(f"room/{key}", val)
    qs.sync()
