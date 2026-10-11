"""Realtime provider construction: one builder per provider, and its config.

Module-level and stateless — the engine's realtime mixin
(``engine_realtime``) calls these to build what one start attempt connects.
Each builder returns ``(provider, voice, model)``; ``transport_audio_profile``
holds the per-provider audio wiring CLAUDE.md documents.
"""

from __future__ import annotations

import logging
from typing import Any

from roomkit_ui.features import REALTIME_PROVIDER_FEATURES, require

logger = logging.getLogger(__name__)

_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"


def realtime_sample_rate(provider_name: str) -> int:
    """Transport sample rate for a realtime provider.

    ElevenLabs ConvAI runs a fixed 16 kHz contract on both legs (roomkit
    raises on anything else); every other provider streams 24 kHz PCM.
    """
    return 16000 if provider_name == "elevenlabs" else 24000


def build_realtime_provider(provider_name: str, settings: dict) -> tuple[Any, str, str]:
    """Instantiate the realtime provider. Returns (provider, voice, model).

    ``voice`` may be ``""`` (ElevenLabs — the agent defines it); callers must
    map that to ``None`` before handing it to the channel.
    """
    feature = REALTIME_PROVIDER_FEATURES.get(provider_name)
    if feature is not None:
        require(feature)

    if provider_name == "openai":
        api_key = settings.get("openai_api_key", "")
        if not api_key:
            raise ValueError("OpenAI API key is required. Open Settings to enter it.")
        model = settings.get("openai_model", "gpt-realtime-2.1")
        voice = settings.get("openai_voice", "alloy")
        from roomkit.providers.openai.realtime import OpenAIRealtimeProvider

        return OpenAIRealtimeProvider(api_key=api_key, model=model), voice, model

    if provider_name == "deepgram":
        return _build_deepgram_agent(settings)

    if provider_name == "elevenlabs":
        return _build_elevenlabs_realtime(settings)

    if provider_name == "xai":
        return _build_xai_realtime(settings)

    if provider_name == "openai_live":
        return _build_openai_live(settings)

    api_key = settings.get("api_key", "")
    if not api_key:
        raise ValueError("Google API key is required. Open Settings to enter it.")
    model = settings.get("model", _GEMINI_DEFAULT_MODEL)
    voice = settings.get("voice", "Aoede")
    from roomkit.providers.gemini.realtime import GeminiLiveProvider

    return GeminiLiveProvider(api_key=api_key, model=model), voice, model


def _deepgram_listen_stage(settings: dict) -> tuple[str, str | None, str | None]:
    """Resolve (listen_model, listen_version, listen_language) from settings.

    Derivations instead of rejections: nova-3 monolingual is English-only,
    so a specific language with no explicit model selects nova-2; the Flux
    models require the ``v2`` listen API version, so it is set whenever a
    flux model is chosen.
    """
    model = (settings.get("deepgram_agent_listen_model", "") or "").strip()
    language = (settings.get("deepgram_agent_listen_language", "") or "").strip() or None
    if not model:
        model = "nova-2" if language and language not in ("en", "multi") else "nova-3"
        if model == "nova-2":
            logger.info("Deepgram listen model derived: nova-2 (language=%s)", language)
    version = "v2" if model.startswith("flux") else None
    return model, version, language


def deepgram_half_duplex(provider_name: str, settings: dict) -> bool:
    """Whether this session should mute the mic during agent playback.

    Deepgram owns turn detection outright (``server_vad=False`` is ignored)
    and exposes no sensitivity knob.  With the example-mirroring transport
    AEC the mic stays open by default; this remains the escape hatch for
    setups whose echo still trips it (loud speakers, no AEC installed).
    """
    return provider_name == "deepgram" and bool(settings.get("deepgram_agent_half_duplex", False))


def transport_audio_profile(
    provider_name: str, aec: Any, sample_rate: int
) -> tuple[Any, Any, int]:
    """Per-provider transport wiring: (transport_aec, pipeline_denoiser, prebuffer_ms).

    Deepgram mirrors roomkit's ``examples/realtime_voice_local_deepgram.py``:
    the AEC runs at transport level — inline on the PortAudio thread, so
    reference and capture stay sample-synchronous.  Deepgram's turn
    detection cannot tell the agent's echo from the caller, and the example
    documents the endless barge-in loop an open, poorly-aligned mic causes.
    A WebRTC noise suppressor rides the pipeline with it.  The playback
    prebuffer grows to absorb Aura's bursty delivery (the mid-response
    underruns seen in the field logs) whatever the AEC: half-duplex mutes
    the mic, not the bursts.  Gemini/OpenAI keep the pipeline-stage AEC,
    mirroring ``examples/realtime_voice_local_gemini.py``.

    GPT-Live mirrors ``examples/realtime_voice_local_openai_live.py``: the
    AEC at transport level too (the example hands it to both, and the
    transport's NATIVE_AEC makes the pipeline skip its copy), a WebRTC noise
    suppressor whether or not there is an AEC, and the default prebuffer.
    Full-duplex keeps the mic open while the model speaks, so the echo path
    must be sample-synchronous; without an AEC the mic is muted instead.
    """
    from roomkit_ui.engine_audio import build_denoiser

    if provider_name == "openai_live":
        return aec, build_denoiser("webrtc", sample_rate), 120
    if provider_name != "deepgram":
        return None, None, 120
    if aec is None:
        return None, None, 240
    return aec, build_denoiser("webrtc", sample_rate), 240


def _deepgram_speak_stage(settings: dict) -> tuple[str, dict | None, dict | None]:
    """Compose ``agent.speak``: Aura by default, or a Deepgram-hosted vendor.

    Deepgram's speak stage accepts third-party TTS with that vendor's own field
    shape (roomkit passes ``speak_provider``/``speak_endpoint`` verbatim). BYO
    vendors authenticate through the endpoint: the ElevenLabs voice id rides in
    the endpoint URL — not the provider dict — with the ``xi-api-key`` header,
    and OpenAI uses its speech endpoint with a bearer token. The keys come from
    the vendor's own provider section, so nothing is entered twice.

    Returns ``(voice_label, speak_provider, speak_endpoint)`` — the label feeds
    the session-info display.
    """
    vendor = (settings.get("deepgram_agent_speak_provider", "") or "").strip()
    model = (settings.get("deepgram_agent_speak_model", "") or "").strip()
    tts_voice = (settings.get("deepgram_agent_speak_voice", "") or "").strip()

    if vendor == "eleven_labs":
        api_key = settings.get("elevenlabs_api_key", "")
        if not api_key:
            raise ValueError(
                "ElevenLabs TTS through Deepgram uses your ElevenLabs API key. "
                "Open Settings and enter it under the ElevenLabs provider."
            )
        if not tts_voice:
            raise ValueError(
                "An ElevenLabs voice ID is required for ElevenLabs TTS. "
                "Open Settings → Advanced → TTS Voice."
            )
        model = model or "eleven_turbo_v2_5"
        endpoint = {
            "url": f"wss://api.elevenlabs.io/v1/text-to-speech/{tts_voice}/multi-stream-input",
            "headers": {"xi-api-key": api_key},
        }
        return f"eleven_labs · {model}", {"type": "eleven_labs", "model_id": model}, endpoint

    if vendor == "open_ai":
        api_key = settings.get("openai_api_key", "")
        if not api_key:
            raise ValueError(
                "OpenAI TTS through Deepgram uses your OpenAI API key. "
                "Open Settings and enter it under the OpenAI provider."
            )
        provider = {"type": "open_ai", "model": model or "tts-1", "voice": tts_voice or "alloy"}
        endpoint = {
            "url": "https://api.openai.com/v1/audio/speech",
            "headers": {"authorization": f"Bearer {api_key}"},
        }
        return f"open_ai · {provider['voice']}", provider, endpoint

    aura_voice = settings.get("deepgram_agent_voice", "") or "aura-2-thalia-en"
    speed_raw = settings.get("deepgram_agent_speak_speed", "")
    if speed_raw:
        try:
            # Deepgram accepts 0.7-1.5 on Aura voices — clamp instead of
            # letting the Settings handshake fail mid-connect.
            speed = min(1.5, max(0.7, float(speed_raw)))
        except (ValueError, TypeError):
            speed = None
        if speed is not None:
            return aura_voice, {"type": "deepgram", "model": aura_voice, "speed": speed}, None
    return aura_voice, None, None


def _build_deepgram_agent(settings: dict) -> tuple[Any, str, str]:
    """Deepgram composes the agent from listen/think/speak stages."""
    api_key = settings.get("deepgram_api_key", "")
    if not api_key:
        raise ValueError("Deepgram API key is required. Open Settings to enter it.")
    voice = settings.get("deepgram_agent_voice", "") or "aura-2-thalia-en"
    voice_label, speak_provider, speak_endpoint = _deepgram_speak_stage(settings)
    think_provider = settings.get("deepgram_agent_think_provider", "") or "open_ai"
    think_model = settings.get("deepgram_agent_think_model", "")
    if not think_model:
        if think_provider != "open_ai":
            # gpt-4o-mini is Deepgram's default for open_ai only — sending it
            # with another think provider is an invalid pairing Deepgram
            # rejects mid-handshake, far less legibly than this.
            raise ValueError(
                f"Deepgram think model is required for the {think_provider} LLM "
                "provider. Open Settings → Advanced to pick one."
            )
        think_model = "gpt-4o-mini"
    listen_model, listen_version, listen_language = _deepgram_listen_stage(settings)

    from roomkit.providers.deepgram.config import DeepgramAgentConfig
    from roomkit.providers.deepgram.realtime import DeepgramAgentProvider

    # Vendor speak stages land after roomkit 0.44.0. Pydantic would silently
    # drop the unknown kwargs on an older roomkit — the session would connect
    # and speak with the wrong voice, so refuse legibly instead.
    speak_kwargs: dict[str, Any] = {}
    if speak_provider is not None:
        if "speak_provider" not in DeepgramAgentConfig.model_fields:
            raise ValueError(
                "Third-party TTS and voice speed for Deepgram need a roomkit "
                "newer than 0.44.0. Update the roomkit dependency, or set "
                "TTS Provider back to Deepgram Aura."
            )
        speak_kwargs = {"speak_provider": speak_provider, "speak_endpoint": speak_endpoint}

    config = DeepgramAgentConfig(
        api_key=api_key,
        listen_model=listen_model,
        listen_version=listen_version,
        listen_language=listen_language,
        think_provider=think_provider,
        think_model=think_model,
        speak_model=voice,
        greeting=settings.get("deepgram_agent_greeting", "") or None,
        **speak_kwargs,
    )
    return DeepgramAgentProvider(config), voice_label, think_model


def _build_elevenlabs_realtime(settings: dict) -> tuple[Any, str, str]:
    """ElevenLabs ConvAI drives a pre-configured agent — no model/voice here."""
    api_key = settings.get("elevenlabs_api_key", "")
    if not api_key:
        raise ValueError("ElevenLabs API key is required. Open Settings to enter it.")
    agent_id = settings.get("elevenlabs_agent_id", "")
    if not agent_id:
        raise ValueError(
            "ElevenLabs Agent ID is required (create an agent on the ElevenLabs "
            "dashboard). Open Settings to enter it."
        )

    from roomkit.providers.elevenlabs.config import ElevenLabsRealtimeConfig
    from roomkit.providers.elevenlabs.realtime import ElevenLabsRealtimeProvider

    config = ElevenLabsRealtimeConfig(api_key=api_key, agent_id=agent_id)
    return ElevenLabsRealtimeProvider(config), "", agent_id


def _build_xai_realtime(settings: dict) -> tuple[Any, str, str]:
    api_key = settings.get("xai_api_key", "")
    if not api_key:
        raise ValueError("xAI API key is required. Open Settings to enter it.")
    model = settings.get("xai_model", "") or "grok-2-audio"
    voice = settings.get("xai_voice", "") or "eve"

    from roomkit.providers.xai.realtime import XAIRealtimeProvider

    return XAIRealtimeProvider(api_key=api_key, model=model), voice, model


# The backend's own instructions — the live model's are the user's system
# prompt.  Adapted from roomkit's examples/realtime_voice_local_openai_live.py,
# minus its demo tools: the backend answers through the live model, which
# speaks the result in its own words.
_GPT_LIVE_BACKEND_INSTRUCTIONS = (
    "You are helping an assistant during a live voice conversation. The request may "
    "contain transcription errors; use the most likely intent. Use the available tools "
    "when they help. Answer in the language the user speaks. Return the verified result "
    "in concise, conversational plain text — no Markdown, no raw JSON — and never claim "
    "an action completed without a tool result confirming it."
)


def _build_openai_live(settings: dict) -> tuple[Any, str, str]:
    """GPT-Live: a full-duplex live model, and a backend OpenAI hosts for tools.

    The live model holds no tools: it delegates reasoning and tool use to the
    backend (``HostedReasoning``), whose function calls reach the channel's
    tool handler like any provider's.
    """
    api_key = settings.get("openai_api_key", "")
    if not api_key:
        raise ValueError("OpenAI API key is required. Open Settings to enter it.")
    model = settings.get("openai_live_model", "") or "gpt-live-1"
    voice = settings.get("openai_live_voice", "") or "marin"

    from roomkit.providers.openai.live import HostedReasoning, OpenAILiveProvider

    backend = HostedReasoning(
        model=settings.get("openai_live_backend_model", "") or "gpt-5.6-terra",
        instructions=_GPT_LIVE_BACKEND_INSTRUCTIONS,
        reasoning_effort=settings.get("openai_live_backend_effort", "") or "low",
    )
    provider = OpenAILiveProvider(api_key=api_key, model=model, delegation=backend)
    return provider, voice, model


def build_provider_config(provider_name: str, settings: dict) -> dict[str, Any]:
    """Assemble provider-specific advanced settings (VAD, proactive audio, etc.)."""
    provider_config: dict[str, Any] = {}
    if provider_name == "gemini":
        provider_config = _gemini_provider_config(settings)
    elif provider_name == "openai":
        td_type = settings.get("openai_turn_detection", "server_vad")
        if td_type in ("server_vad", "semantic_vad"):
            provider_config["turn_detection_type"] = td_type
            if td_type == "semantic_vad":
                _apply_openai_semantic_vad(provider_config, settings)
            elif td_type == "server_vad":
                _apply_server_vad(provider_config, settings, "openai")
            if not settings.get("openai_interrupt_response", True):
                provider_config["interrupt_response"] = False
            if not settings.get("openai_create_response", True):
                provider_config["create_response"] = False
        else:
            # "none" — disable turn detection entirely
            provider_config["turn_detection_type"] = None
        # Independent of turn detection; omitted unless set so non-reasoning
        # models (gpt-4o-realtime) keep working untouched.
        effort = settings.get("openai_reasoning_effort", "")
        if effort:
            provider_config["reasoning_effort"] = effort
        speed = settings.get("openai_voice_speed", "")
        if speed:
            try:
                # audio.output.speed accepts 0.25–1.5 — clamp instead of
                # letting the API reject the whole session.update.
                provider_config["speed"] = min(1.5, max(0.25, float(speed)))
            except (ValueError, TypeError):
                pass
    elif provider_name == "xai":
        # Wire-compatible with OpenAI's server VAD; xAI honours the same
        # three tuning keys (no semantic VAD, no disabling).
        _apply_server_vad(provider_config, settings, "xai")
    return provider_config


def _gemini_provider_config(settings: dict) -> dict[str, Any]:
    """Gemini Live's provider_config: speech language, turn taking, and the
    options that depend on the model's generation."""
    provider_config: dict[str, Any] = {}
    lang = settings.get("gemini_language", "")
    if lang:
        provider_config["language"] = lang
    if settings.get("gemini_no_interruption"):
        provider_config["no_interruption"] = True
    # enable_affective_dialog: not yet supported by the Gemini API
    # (serialized under generation_config, rejected with 1007), and removed
    # from it with the 3.8 family.  Uncomment if a model brings it back.
    # if settings.get("gemini_affective_dialog"):
    #     provider_config["enable_affective_dialog"] = True
    start_sens = settings.get("gemini_start_sensitivity", "")
    if start_sens:
        provider_config["start_of_speech_sensitivity"] = start_sens
    end_sens = settings.get("gemini_end_sensitivity", "")
    if end_sens:
        provider_config["end_of_speech_sensitivity"] = end_sens
    silence_ms = settings.get("gemini_silence_duration_ms", "")
    if silence_ms:
        try:
            provider_config["silence_duration_ms"] = int(silence_ms)
        except (ValueError, TypeError):
            pass
    _apply_gemini_generation(provider_config, settings)
    return provider_config


def _apply_gemini_generation(provider_config: dict[str, Any], settings: dict) -> None:
    """Add what the session's Gemini Live model accepts, per roomkit's profile.

    Gemini 3.8 Live changed the contract (roomkit 0.79): proactive audio is
    permanent (stating it is refused) and affective dialog is gone, while
    ``gemini-3.8-live-extended-thinking`` takes a thinking level and the
    3.8 family a transcription block.  roomkit drops a refused field with a
    warning in the log; filtering here keeps a setting from being a silent
    no-op on one model and sent on another.
    """
    from roomkit.providers.gemini.realtime_models import PRE_38_PROFILE, live_model_profile

    profile = live_model_profile(settings.get("model", "") or _GEMINI_DEFAULT_MODEL)
    if settings.get("gemini_proactive_audio") and profile.proactivity:
        provider_config["proactive_audio"] = True
    level = (settings.get("gemini_thinking_level", "") or "").upper()
    if level and profile.thinking_level:
        provider_config["thinking_level"] = level
    if profile is not PRE_38_PROFILE:
        transcription = _gemini_transcription(settings)
        if transcription:
            provider_config["transcription"] = transcription


def _gemini_transcription(settings: dict) -> dict[str, Any]:
    """The 3.8 transcription block: how the server hears the user's speech."""
    block: dict[str, Any] = {}
    if settings.get("gemini_language_auto"):
        block["language_auto"] = True
    hints = _comma_list(settings.get("gemini_language_hints", ""))
    if hints:
        block["language_hints"] = hints
    vocabulary = _comma_list(settings.get("gemini_custom_vocabulary", ""))
    if vocabulary:
        block["custom_vocabulary"] = vocabulary
    return block


def _comma_list(raw: Any) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _apply_openai_semantic_vad(provider_config: dict[str, Any], settings: dict) -> None:
    eagerness = settings.get("openai_eagerness", "")
    if eagerness:
        try:
            provider_config["eagerness"] = float(eagerness)
        except (ValueError, TypeError):
            pass


def _apply_server_vad(provider_config: dict[str, Any], settings: dict, prefix: str) -> None:
    """Copy the ``{prefix}_*`` server-VAD tuning settings into provider_config."""
    threshold = settings.get(f"{prefix}_vad_threshold", "")
    if threshold:
        try:
            provider_config["threshold"] = float(threshold)
        except (ValueError, TypeError):
            pass
    silence_ms = settings.get(f"{prefix}_silence_duration_ms", "")
    if silence_ms:
        try:
            provider_config["silence_duration_ms"] = int(silence_ms)
        except (ValueError, TypeError):
            pass
    prefix_ms = settings.get(f"{prefix}_prefix_padding_ms", "")
    if prefix_ms:
        try:
            provider_config["prefix_padding_ms"] = int(prefix_ms)
        except (ValueError, TypeError):
            pass
