"""QSettings persistence for app configuration."""

from __future__ import annotations

import json
import re
import sys
import uuid
from collections.abc import Callable
from functools import partial
from typing import Any
from urllib.parse import urlsplit

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
# Words of an env var name (split on non-alphanumerics) that mark its value as
# a credential, for MCP servers and CLI tools alike. A value is also a secret
# when it is a URL carrying credentials, whatever the name (_is_env_secret).
_ENV_SECRET_MARKERS = frozenset(
    {
        "APIKEY",
        "AUTH",
        "BEARER",
        "CREDENTIAL",
        "CREDENTIALS",
        "DSN",
        "KEY",
        "PASS",
        "PASSPHRASE",
        "PASSWD",
        "PASSWORD",
        "PAT",
        "PWD",
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
    "vc_anthropic_model": "claude-sonnet-5-5",
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
    "vad_speech_pad_ms": "",  # pre-roll buffer in ms (empty = 1000, roomkit 0.90+)
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
}


# Defaults the vendor retires: (retired default, its successor, the notice).
# The Settings dialog saves every field on close, so a stored value equal to
# a retired default is, almost always, that default and not a deliberate
# pick.  It moves on with the default, and the chat says so once — a pick
# that happens to match can be made again.  Dates from roomkit 0.96.1's
# Anthropic catalog: Sonnet 4.5 deprecated 2026-09-30, retiring 2026-11-30.
_RETIRED_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "vc_anthropic_model": (
        "claude-sonnet-4-5-20250929",
        "claude-sonnet-5-5",
        "Claude Sonnet 4.5 retires on 2026-11-30: the voice channel now uses "
        "Claude Sonnet 5.5. Pick another model in Settings → AI Provider → LLM.",
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


def _settings_secret_name(key: str) -> str:
    return f"settings:{key}"


def _mcp_server_secret_name(server_id: str, field: str) -> str:
    return f"mcp_server:{server_id}:{field}"


def _mcp_server_env_secret_name(server_id: str, key: str) -> str:
    return f"mcp_server:{server_id}:env:{key}"


def _mcp_server_env_legacy_names(legacy_ids: list[str], key: str) -> list[str]:
    return [_mcp_server_env_secret_name(old_id, key) for old_id in legacy_ids]


def _cli_tool_env_secret_name(tool_id: str, key: str) -> str:
    return f"cli_tool:{tool_id}:env:{key}"


def _mcp_oauth_secret_name(server_id: str, suffix: str) -> str:
    return f"mcp_oauth:{server_id}:{suffix}"


def _ensure_entry_id(entry: dict[str, Any]) -> tuple[str, bool]:
    """Return the stable id of an MCP server / CLI tool, minting one if absent."""
    entry_id = str(entry.get("id", "") or "").strip()
    if entry_id:
        return entry_id, False
    entry_id = uuid.uuid4().hex
    entry["id"] = entry_id
    return entry_id, True


def _legacy_server_identities(server_id: str, server_name: str) -> list[str]:
    legacy: list[str] = []
    if server_name and server_name != server_id:
        legacy.append(server_name)
    return legacy


def _is_env_secret(key: str, value: str = "") -> bool:
    """Whether an env line holds a credential — by its name, or by its value."""
    parts = {part for part in re.split(r"[^A-Z0-9]+", key.upper()) if part}
    if parts & _ENV_SECRET_MARKERS:
        return True
    if "DATABASE" in parts and parts & {"URL", "URI"}:
        return True
    return _url_has_credentials(value)


def _url_has_credentials(value: str) -> bool:
    """``scheme://user:password@host`` (or a token as the user) is a secret."""
    try:
        split = urlsplit(value.strip())
    except ValueError:
        return False
    return bool(split.scheme and split.netloc and (split.username or split.password))


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


def _hydrate_env(
    raw: Any,
    store: SecretStore,
    secret_name: Callable[[str], str],
    legacy_names: Callable[[str], list[str]] = lambda _key: [],
) -> tuple[str, bool]:
    """Fill an env block's secret values back in from *store*.

    A secret is stored as ``KEY=`` in QSettings, so every empty value is
    looked up — the name alone cannot say which ones were secrets, since a
    URL carrying a password is one whatever it is called. A secret still in
    plain text is moved to *store*; the returned flag says one was.
    """
    if not isinstance(raw, str) or not raw.strip():
        return "" if raw is None else str(raw or ""), False

    migrated = False
    out: list[str] = []
    for line in raw.splitlines():
        if "=" not in line:
            out.append(line)
            continue
        key, value = line.split("=", 1)
        env_key, value_text = key.strip(), value.strip()
        if not env_key or (value_text and not _is_env_secret(env_key, value_text)):
            out.append(line)
            continue

        name = secret_name(env_key)
        stored = _get_secret_with_legacy(store, name, legacy_names(env_key))
        if value_text:
            if not stored:
                store.set_secret(name, value_text)
            migrated = True
        elif stored:
            value_text = stored

        out.append(f"{env_key}={value_text}")
    return "\n".join(out), migrated


def _sanitize_env(
    raw: Any, store: SecretStore, secret_name: Callable[[str], str], *, persist: bool
) -> str:
    """Strip an env block's secret values, moving them to *store* if *persist*.

    An emptied value deletes its stored secret, or loading would bring the
    old one back (``_hydrate_env`` fills every empty value it can).
    """
    if not isinstance(raw, str) or not raw.strip():
        return "" if raw is None else str(raw or "")

    out: list[str] = []
    for line in raw.splitlines():
        if "=" not in line:
            out.append(line)
            continue
        key, value = line.split("=", 1)
        env_key, value_text = key.strip(), value.strip()
        if not env_key or (value_text and not _is_env_secret(env_key, value_text)):
            out.append(line)
            continue

        if persist:
            if value_text:
                store.set_secret(secret_name(env_key), value_text)
            else:
                store.delete_secret(secret_name(env_key))
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


def _parse_json_list(raw: Any) -> list[Any] | None:
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
    servers = _parse_json_list(raw)
    if servers is None:
        return raw

    migrated = False
    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id, created_id = _ensure_entry_id(server)
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
        hydrated_env, env_migrated = _hydrate_env(
            server.get("env", ""),
            store,
            partial(_mcp_server_env_secret_name, server_id),
            partial(_mcp_server_env_legacy_names, legacy_ids),
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
    servers = _parse_json_list(raw)
    if servers is None:
        return raw

    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id, _created_id = _ensure_entry_id(server)
        if "env" in server:
            server["env"] = _sanitize_env(
                server.get("env", ""),
                store,
                partial(_mcp_server_env_secret_name, server_id),
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


def _hydrate_cli_tool_secrets(raw: Any, qs: QSettings, store: SecretStore) -> Any:
    """Return cli_tools JSON with env secrets filled from SecretStore.

    Same contract as ``_hydrate_mcp_server_secrets``: plaintext secrets left
    by an older version are moved out of QSettings on the way.
    """
    tools = _parse_json_list(raw)
    if tools is None:
        return raw

    migrated = False
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool_id, created_id = _ensure_entry_id(tool)
        env, env_migrated = _hydrate_env(
            tool.get("env", ""), store, partial(_cli_tool_env_secret_name, tool_id)
        )
        if env != tool.get("env", ""):
            tool["env"] = env
        migrated = migrated or created_id or env_migrated

    if migrated:
        qs.setValue("room/cli_tools", _sanitize_cli_tools(json.dumps(tools), store, persist=False))
        qs.sync()
    return json.dumps(tools)


def _sanitize_cli_tools(raw: Any, store: SecretStore, *, persist: bool) -> Any:
    """Move CLI tool env secrets into SecretStore and return sanitized JSON."""
    tools = _parse_json_list(raw)
    if tools is None:
        return raw

    for tool in tools:
        if not isinstance(tool, dict) or "env" not in tool:
            continue
        tool_id, _created_id = _ensure_entry_id(tool)
        tool["env"] = _sanitize_env(
            tool.get("env", ""),
            store,
            partial(_cli_tool_env_secret_name, tool_id),
            persist=persist,
        )
    return json.dumps(tools)


def load_settings() -> dict:
    """Load persisted settings, falling back to defaults."""
    qs = QSettings()
    store = get_secret_store()
    out: dict = {}
    for key, default in _DEFAULTS.items():
        if key in _SECRET_KEYS:
            out[key] = _load_secret_setting(qs, store, key)
            continue

        _migrate_retired_default(qs, key)
        val = qs.value(f"room/{key}", default)
        if key == "mcp_servers":
            val = _hydrate_mcp_server_secrets(val, qs, store)
        elif key == "cli_tools":
            val = _hydrate_cli_tool_secrets(val, qs, store)
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
            _save_secret_setting(qs, store, key, val)
            continue
        if key == "mcp_servers":
            val = _sanitize_mcp_servers(val, store, persist=True)
        elif key == "cli_tools":
            val = _sanitize_cli_tools(val, store, persist=True)
        qs.setValue(f"room/{key}", val)
    qs.sync()
