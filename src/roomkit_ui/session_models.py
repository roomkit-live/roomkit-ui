"""Display-only inventory of the models a running session actually uses.

RoomKit's voice backends expose their resolved configuration as ``_config``.
Keep that SDK boundary here and read only named, non-secret fields; never
serialize a config, client, endpoint or the user's settings into the UI.
Local ONNX models use the catalogue id (their config contains file paths).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict


class SessionModel(TypedDict):
    role: str
    provider: str
    model: str
    description: str


def _text(obj: Any, *fields: str) -> str:
    for field in fields:
        value = getattr(obj, field, None)
        if isinstance(value, str) and value:
            return value
    return ""


def _part(role: str, provider: str, model: str, *details: str) -> SessionModel:
    return SessionModel(
        role=role,
        provider=provider,
        model=model or "Model not reported",
        description="\n".join(detail for detail in details if detail),
    )


def _language(config: Any) -> str:
    language = _text(config, "language")
    for field in ("language_codes", "language_bias"):
        values = getattr(config, field, None)
        if isinstance(values, list) and all(isinstance(v, str) for v in values):
            language = ", ".join(values) or language
    return f"Language · {language}" if language else "Language · Automatic"


def decision_model(policy: str, classifier: Any, llm: Any, llm_provider: str) -> SessionModel:
    """Inspect only the classifier that was successfully installed on the agent."""
    if policy == "llm":
        return _part(
            "Speaking decision",
            llm_provider,
            _text(llm, "model_name"),
            "Uses the conversation model.",
        )
    if policy == "jev":
        config = getattr(getattr(classifier, "_client", None), "_config", None)
        return _part("Speaking decision", "typesafe", _text(config, "default_model"))
    return _part("Speaking decision", "openai", _text(classifier, "_model"))


def voice_channel_models(
    settings: dict, *, stt: Any, stt_provider: str, llm: Any, tts: Any, agent: Any
) -> list[SessionModel]:
    stt_config = getattr(stt, "_config", None)
    stt_model = (
        settings.get("vc_stt_model", "")
        if stt_provider == "local"
        else _text(stt_config, "model", "model_name", "deployment")
    )
    llm_provider = settings.get("vc_llm_provider", "anthropic")
    models = [
        _part("Listen · STT", stt_provider, stt_model, _language(stt_config)),
        _part("Reason · LLM", llm_provider, _text(llm, "model_name")),
        _tts_model(settings, tts),
    ]
    if agent.decision is not None:
        models.append(agent.decision)
    else:
        models.append(_part("Speaking decision", "", "Always answer", "No decision model active."))
    if agent.thinker is not None:
        models.append(
            _part(
                "Think while listening",
                llm_provider,
                _text(llm, "model_name"),
                "Uses the conversation model.",
            )
        )
    elif settings.get("vc_thinker"):
        models.append(
            _part(
                "Think while listening",
                "",
                "Inactive",
                "Requires an active speaking decision and a model with structured responses.",
            )
        )
    return models


def _tts_model(settings: dict, tts: Any) -> SessionModel:
    provider = settings.get("vc_tts_provider", "piper")
    config = getattr(tts, "_config", None)
    model = _text(config, "model", "model_id", "model_name", "backbone_repo")
    voice = _text(tts, "default_voice")
    extra = ""
    if provider == "piper":
        model = settings.get("vc_tts_model", "")
    elif provider == "pocket":
        model = _text(config, "language")
        voices = getattr(config, "voices", {})
        source = voices.get(voice, "") if isinstance(voices, dict) else ""
        if isinstance(source, str) and source:
            voice = f"Cloned · {Path(source).name}" if "/" in source or "\\" in source else source
    elif provider in {"qwen3", "neutts"}:
        voice = "Cloned voice"
        codec = _text(config, "codec_repo")
        extra = f"Codec · {codec}" if codec else ""
    elif provider == "azure":
        # Azure chooses the model through the voice name, not a model field.
        model = voice.partition(":")[2] or "Azure neural voice"
    return _part("Speak · TTS", provider, model, f"Voice · {voice}" if voice else "", extra)


def realtime_models(
    provider_name: str,
    provider: Any,
    *,
    model: str,
    voice: str,
    settings: dict,
    provider_config: dict,
) -> list[SessionModel]:
    if provider_name == "deepgram":
        models = _deepgram_models(provider, settings)
    elif provider_name == "elevenlabs":
        models = [
            _part(
                "Realtime agent",
                provider_name,
                model,
                "STT, LLM, TTS and voice are configured in ElevenLabs. "
                "Their names are not reported by this connection.",
            )
        ]
    else:
        models = [
            _part(
                "Live audio",
                provider_name,
                model,
                "Listens, reasons and speaks.",
                f"Voice · {voice}" if voice else "",
            )
        ]
        if provider_name == "openai_live":
            backend = getattr(provider, "delegation", None)
            effort = _text(backend, "reasoning_effort")
            models.append(
                _part(
                    "Reasoning & tools · LLM",
                    "openai",
                    _text(backend, "model"),
                    f"Reasoning effort · {effort}" if effort else "",
                )
            )
        elif provider_name == "openai":
            # RoomKit's OpenAIRealtimeProvider._build_session_config default.
            # The audio model hears speech directly; this renders the transcript.
            models.append(
                _part(
                    "Transcription",
                    "openai",
                    provider_config.get("stt_model", "gpt-4o-transcribe"),
                    "For the displayed transcript; the live model hears audio directly.",
                )
            )
    turn = "Managed by provider"
    if provider_name == "openai":
        turn = {"semantic_vad": "Semantic VAD", "server_vad": "Server VAD", None: "Manual"}.get(
            provider_config.get("turn_detection_type", "server_vad"), "Managed by provider"
        )
    elif provider_name == "xai":
        turn = "Server VAD"
    elif provider_name == "openai_live":
        turn = "Full duplex"
    models.append(
        _part("Speaking decision", provider_name, turn, "Built into the realtime session.")
    )
    return models


def _deepgram_models(provider: Any, settings: dict) -> list[SessionModel]:
    config = getattr(provider, "_config", None)
    speak = getattr(config, "speak_provider", None) or {}
    vendor = speak.get("type", "deepgram")
    model = speak.get("model") or speak.get("model_id") or _text(config, "speak_model")
    voice = speak.get("voice", "")
    if vendor == "eleven_labs":
        # Voice id is otherwise buried in the authenticated endpoint URL.
        voice = settings.get("deepgram_agent_speak_voice", "")
    language = _text(config, "listen_language") or "en"
    return [
        _part("Listen · STT", "deepgram", _text(config, "listen_model"), f"Language · {language}"),
        _part("Reason · LLM", _text(config, "think_provider"), _text(config, "think_model")),
        _part("Speak · TTS", vendor, model, f"Voice · {voice}" if voice else ""),
    ]
