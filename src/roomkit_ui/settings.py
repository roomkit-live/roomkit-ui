"""QSettings persistence for app configuration."""

from __future__ import annotations

import json
import re
import sys
import uuid
from typing import Any

from PySide6.QtCore import QSettings

from roomkit_ui.secret_store import SecretStore, get_secret_store

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
    }
)

_MCP_SERVER_SECRET_FIELDS = ("oauth_client_secret",)
_MCP_ENV_SECRET_MARKERS = frozenset(
    {
        "AUTH",
        "CREDENTIAL",
        "CREDENTIALS",
        "KEY",
        "PASS",
        "PASSWORD",
        "SECRET",
        "TOKEN",
    }
)
_MCP_OAUTH_SECRET_SUFFIXES = ("tokens", "client_info")

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
    "telemetry_provider": "none",  # "none" | "console" | "otlp"
    "otlp_endpoint": "",  # OTLP gRPC endpoint (e.g. http://localhost:4317)
    "otlp_protocol": "grpc",  # "grpc" | "http"
    "otlp_service_name": "roomkit-ui",
    # Audio debug & recording
    "debug_taps_enabled": False,
    "debug_taps_stages": "all",  # "all" or comma-separated: "raw,post_denoiser,..."
    "debug_output_dir": "",  # empty = ~/.local/share/roomkit-ui/debug_audio/
    "recording_enabled": False,
    "recording_mode": "both",  # "inbound_only" | "outbound_only" | "both"
    "recording_channels": "stereo",  # "mixed" | "separate" | "stereo"
    "recording_output_dir": "",  # empty = ~/.local/share/roomkit-ui/recordings/
    "theme": "dark",
    "mcp_servers": "[]",
    # JSON array of {enabled, name, command, description, seed_help, help_depth, timeout}
    "cli_tools": "[]",
    # Voice channel (STT → LLM → TTS) settings
    "conversation_mode": "realtime",  # "realtime" | "voice_channel"
    "vc_llm_provider": "anthropic",  # "anthropic" | "openai" | "gemini"
    "anthropic_api_key": "",
    "vc_anthropic_model": "claude-sonnet-4-5-20250929",
    "vc_openai_model": "gpt-4o",
    "vc_gemini_model": "gemini-2.0-flash",
    "vc_stt_provider": "local",  # "local" | "gradium"
    "vc_tts_provider": "piper",  # "piper" | "qwen3" | "neutts" | "gradium" | "elevenlabs"
    "elevenlabs_api_key": "",
    "elevenlabs_voice_id": "",  # Empty = Rachel default (21m00Tcm4TlvDq8ikWAM)
    "elevenlabs_model": "",  # Empty = eleven_v3
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
    "vad_speech_pad_ms": "",  # pre-roll buffer in ms (empty = 300)
    "vad_energy_silence_rms": "",  # energy fast-exit RMS threshold (empty = 20, 0 = off)
    "vc_turn_detector": "",  # "" (none) or "smart-turn"
    "vc_turn_threshold": "",  # 0.0–1.0 (empty = 0.5)
    "vc_interruption": False,
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
    # Deepgram Voice Agent (realtime speech-to-speech; distinct from VC STT keys)
    "deepgram_agent_voice": "aura-2-thalia-en",  # Aura speak model
    "deepgram_agent_think_provider": "open_ai",  # "open_ai" | "anthropic" | "google"
    "deepgram_agent_think_model": "",  # empty = Deepgram default (gpt-4o-mini)
    "deepgram_agent_listen_language": "",  # e.g. "fr", "multi" (empty = default)
    "deepgram_agent_greeting": "",  # optional line spoken at session open
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
}


def _settings_secret_name(key: str) -> str:
    return f"settings:{key}"


def _mcp_server_secret_name(server_id: str, field: str) -> str:
    return f"mcp_server:{server_id}:{field}"


def _mcp_server_env_secret_name(server_id: str, key: str) -> str:
    return f"mcp_server:{server_id}:env:{key}"


def _mcp_oauth_secret_name(server_id: str, suffix: str) -> str:
    return f"mcp_oauth:{server_id}:{suffix}"


def _ensure_mcp_server_id(server: dict[str, Any]) -> tuple[str, bool]:
    server_id = str(server.get("id", "") or "").strip()
    if server_id:
        return server_id, False
    server_id = uuid.uuid4().hex
    server["id"] = server_id
    return server_id, True


def _legacy_server_identities(server_id: str, server_name: str) -> list[str]:
    legacy: list[str] = []
    if server_name and server_name != server_id:
        legacy.append(server_name)
    return legacy


def _is_mcp_env_secret_key(key: str) -> bool:
    parts = [part for part in re.split(r"[^A-Z0-9]+", key.upper()) if part]
    return any(part in _MCP_ENV_SECRET_MARKERS for part in parts)


def _get_secret_with_legacy(
    store: SecretStore,
    secret_name: str,
    legacy_names: list[str],
) -> str:
    stored = store.get_secret(secret_name, "")
    if stored:
        return stored
    for legacy_name in legacy_names:
        legacy_value = store.get_secret(legacy_name, "")
        if legacy_value:
            store.set_secret(secret_name, legacy_value)
            store.delete_secret(legacy_name)
            return legacy_value
    return ""


def _hydrate_mcp_env(
    raw: Any,
    store: SecretStore,
    server_id: str,
    server_name: str,
) -> tuple[str, bool]:
    if not isinstance(raw, str) or not raw.strip():
        return "" if raw is None else str(raw or ""), False

    migrated = False
    out: list[str] = []
    legacy_ids = _legacy_server_identities(server_id, server_name)
    for line in raw.splitlines():
        if "=" not in line:
            out.append(line)
            continue
        key, value = line.split("=", 1)
        env_key = key.strip()
        if not env_key or not _is_mcp_env_secret_key(env_key):
            out.append(line)
            continue

        secret_name = _mcp_server_env_secret_name(server_id, env_key)
        legacy_names = [_mcp_server_env_secret_name(old_id, env_key) for old_id in legacy_ids]
        stored = _get_secret_with_legacy(store, secret_name, legacy_names)
        value_text = value.strip()
        if value_text:
            if not stored:
                store.set_secret(secret_name, value_text)
                stored = value_text
            migrated = True
        elif stored:
            value_text = stored

        out.append(f"{env_key}={value_text}")
    return "\n".join(out), migrated


def _sanitize_mcp_env(raw: Any, store: SecretStore, server_id: str, *, persist: bool) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return "" if raw is None else str(raw or "")

    out: list[str] = []
    for line in raw.splitlines():
        if "=" not in line:
            out.append(line)
            continue
        key, value = line.split("=", 1)
        env_key = key.strip()
        if not env_key or not _is_mcp_env_secret_key(env_key):
            out.append(line)
            continue

        if persist:
            secret_name = _mcp_server_env_secret_name(server_id, env_key)
            value_text = value.strip()
            if value_text:
                store.set_secret(secret_name, value_text)
            else:
                store.delete_secret(secret_name)
        out.append(f"{env_key}=")
    return "\n".join(out)


def _load_secret_setting(qs: QSettings, store: SecretStore, key: str) -> str:
    """Load a setting-backed secret and migrate any legacy plaintext value."""
    legacy_key = f"room/{key}"
    raw = qs.value(legacy_key, None)
    secret_name = _settings_secret_name(key)
    stored = store.get_secret(secret_name, "")

    if raw is not None:
        raw_value = str(raw)
        if raw_value and not stored:
            store.set_secret(secret_name, raw_value)
            stored = raw_value
        qs.remove(legacy_key)
        qs.sync()
    return stored


def _save_secret_setting(qs: QSettings, store: SecretStore, key: str, value: Any) -> None:
    """Persist a secret in SecretStore and remove any plaintext QSettings copy."""
    secret_name = _settings_secret_name(key)
    text = "" if value is None else str(value)
    if text:
        store.set_secret(secret_name, text)
    else:
        store.delete_secret(secret_name)
    qs.remove(f"room/{key}")


def _parse_mcp_servers(raw: Any) -> list[Any] | None:
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, list) else None


def _hydrate_mcp_server_secrets(raw: Any, qs: QSettings, store: SecretStore) -> Any:
    """Return mcp_servers JSON with secrets filled from SecretStore.

    Legacy plaintext secrets are migrated out of QSettings as a side effect.
    The returned JSON still contains the secret values so existing UI and
    connection code can keep consuming one settings dict.
    """
    servers = _parse_mcp_servers(raw)
    if servers is None:
        return raw

    migrated = False
    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id, created_id = _ensure_mcp_server_id(server)
        migrated = migrated or created_id
        server_name = str(server.get("name", "")).strip()
        legacy_ids = _legacy_server_identities(server_id, server_name)
        for field in _MCP_SERVER_SECRET_FIELDS:
            secret_name = _mcp_server_secret_name(server_id, field)
            legacy_names = [_mcp_server_secret_name(old_id, field) for old_id in legacy_ids]
            legacy_value = str(server.get(field, "") or "")
            stored = _get_secret_with_legacy(store, secret_name, legacy_names)
            if legacy_value:
                if not stored:
                    store.set_secret(secret_name, legacy_value)
                    stored = legacy_value
                server[field] = stored
                migrated = True
            elif stored:
                server[field] = stored
        hydrated_env, env_migrated = _hydrate_mcp_env(
            server.get("env", ""),
            store,
            server_id,
            server_name,
        )
        if hydrated_env != server.get("env", ""):
            server["env"] = hydrated_env
        migrated = migrated or env_migrated

        for suffix in _MCP_OAUTH_SECRET_SUFFIXES:
            secret_name = _mcp_oauth_secret_name(server_id, suffix)
            legacy_names = [_mcp_oauth_secret_name(old_id, suffix) for old_id in legacy_ids]
            if _get_secret_with_legacy(store, secret_name, legacy_names):
                migrated = True

    if migrated:
        sanitized = _sanitize_mcp_servers(json.dumps(servers), store, persist=False)
        qs.setValue("room/mcp_servers", sanitized)
        qs.sync()
    return json.dumps(servers)


def _sanitize_mcp_servers(raw: Any, store: SecretStore, *, persist: bool) -> Any:
    """Move MCP server secrets into SecretStore and return sanitized JSON."""
    servers = _parse_mcp_servers(raw)
    if servers is None:
        return raw

    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id, _created_id = _ensure_mcp_server_id(server)
        if "env" in server:
            server["env"] = _sanitize_mcp_env(
                server.get("env", ""),
                store,
                server_id,
                persist=persist,
            )
        for field in _MCP_SERVER_SECRET_FIELDS:
            if field not in server:
                continue
            secret_name = _mcp_server_secret_name(server_id, field)
            value = str(server.get(field, "") or "")
            if persist:
                if value:
                    store.set_secret(secret_name, value)
                else:
                    store.delete_secret(secret_name)
            server[field] = ""
    return json.dumps(servers)


def load_settings() -> dict:
    """Load persisted settings, falling back to defaults."""
    qs = QSettings()
    store = get_secret_store()
    out: dict = {}
    for key, default in _DEFAULTS.items():
        if key in _SECRET_KEYS:
            out[key] = _load_secret_setting(qs, store, key)
            continue

        val = qs.value(f"room/{key}", default)
        if key == "mcp_servers":
            val = _hydrate_mcp_server_secrets(val, qs, store)
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
        out[key] = val
    return out


def save_settings(settings: dict) -> None:
    """Persist settings to disk."""
    qs = QSettings()
    store = get_secret_store()
    for key, val in settings.items():
        if key in _SECRET_KEYS:
            _save_secret_setting(qs, store, key, val)
            continue
        if key == "mcp_servers":
            val = _sanitize_mcp_servers(val, store, persist=True)
        qs.setValue(f"room/{key}", val)
    qs.sync()
