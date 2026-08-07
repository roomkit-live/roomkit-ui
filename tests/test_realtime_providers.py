"""Realtime provider construction dispatch (engine_realtime helpers)."""

import pytest

from roomkit_ui.engine_realtime import (
    _build_provider_config,
    _build_realtime_provider,
    _deepgram_half_duplex,
    _deepgram_listen_stage,
    _realtime_sample_rate,
)

# -- sample rate ------------------------------------------------------------


def test_elevenlabs_runs_at_16khz():
    assert _realtime_sample_rate("elevenlabs") == 16000


@pytest.mark.parametrize("provider", ["gemini", "openai", "deepgram", "xai"])
def test_other_providers_run_at_24khz(provider):
    assert _realtime_sample_rate(provider) == 24000


# -- missing credentials fail with an actionable message ---------------------


@pytest.mark.parametrize(
    ("provider", "settings", "match"),
    [
        ("gemini", {}, "Google API key"),
        ("openai", {}, "OpenAI API key"),
        ("deepgram", {}, "Deepgram API key"),
        ("elevenlabs", {}, "ElevenLabs API key"),
        ("elevenlabs", {"elevenlabs_api_key": "k"}, "Agent ID"),
        ("xai", {}, "xAI API key"),
    ],
)
def test_missing_credentials_raise(provider, settings, match):
    with pytest.raises(ValueError, match=match):
        _build_realtime_provider(provider, settings)


# -- construction -----------------------------------------------------------


def test_deepgram_builds_with_defaults():
    provider, voice, model = _build_realtime_provider("deepgram", {"deepgram_api_key": "k"})
    assert type(provider).__name__ == "DeepgramAgentProvider"
    assert voice == "aura-2-thalia-en"
    assert model == "gpt-4o-mini"


def test_deepgram_settings_reach_the_config():
    provider, voice, model = _build_realtime_provider(
        "deepgram",
        {
            "deepgram_api_key": "k",
            "deepgram_agent_voice": "aura-2-agathe-fr",
            "deepgram_agent_think_provider": "anthropic",
            "deepgram_agent_think_model": "claude-3-5-haiku-latest",
            "deepgram_agent_listen_language": "fr",
            "deepgram_agent_greeting": "Bonjour!",
        },
    )
    config = provider._config
    assert voice == "aura-2-agathe-fr"
    assert model == "claude-3-5-haiku-latest"
    assert config.speak_model == "aura-2-agathe-fr"
    assert config.think_provider == "anthropic"
    assert config.listen_language == "fr"
    assert config.greeting == "Bonjour!"


def test_deepgram_listen_stage_defaults_to_nova3_english():
    assert _deepgram_listen_stage({}) == ("nova-3", None, None)


def test_deepgram_language_without_model_derives_nova2():
    model, version, language = _deepgram_listen_stage({"deepgram_agent_listen_language": "fr"})
    assert model == "nova-2"
    assert version is None
    assert language == "fr"


def test_deepgram_multilingual_stays_on_nova3():
    model, _, language = _deepgram_listen_stage({"deepgram_agent_listen_language": "multi"})
    assert model == "nova-3"
    assert language == "multi"


def test_deepgram_explicit_model_wins_over_derivation():
    model, _, _ = _deepgram_listen_stage(
        {"deepgram_agent_listen_model": "nova-3", "deepgram_agent_listen_language": "fr"}
    )
    assert model == "nova-3"


def test_deepgram_flux_gets_the_v2_listen_version():
    model, version, _ = _deepgram_listen_stage({"deepgram_agent_listen_model": "flux-general-en"})
    assert model == "flux-general-en"
    assert version == "v2"


def test_deepgram_listen_settings_reach_the_config():
    provider, _, _ = _build_realtime_provider(
        "deepgram",
        {"deepgram_api_key": "k", "deepgram_agent_listen_language": "fr"},
    )
    assert provider._config.listen_model == "nova-2"
    assert provider._config.listen_language == "fr"


def test_half_duplex_is_deepgram_only_and_defaults_off():
    # Default wiring mirrors roomkit's deepgram example (transport AEC, open
    # mic); half-duplex is the opt-in escape hatch.
    assert _deepgram_half_duplex("deepgram", {}) is False
    assert _deepgram_half_duplex("deepgram", {"deepgram_agent_half_duplex": True}) is True
    assert _deepgram_half_duplex("gemini", {"deepgram_agent_half_duplex": True}) is False


def test_transport_profile_deepgram_mirrors_the_example():
    from roomkit_ui.engine_realtime import _transport_audio_profile

    aec = object()
    transport_aec, denoiser, prebuffer = _transport_audio_profile("deepgram", aec, 24000)
    assert transport_aec is aec
    assert denoiser is not None  # webrtc noise suppressor
    assert prebuffer == 240


def test_transport_profile_gemini_keeps_pipeline_aec():
    from roomkit_ui.engine_realtime import _transport_audio_profile

    transport_aec, denoiser, prebuffer = _transport_audio_profile("gemini", object(), 24000)
    assert transport_aec is None
    assert denoiser is None
    assert prebuffer == 120


def test_transport_profile_deepgram_without_aec_stays_default():
    from roomkit_ui.engine_realtime import _transport_audio_profile

    assert _transport_audio_profile("deepgram", None, 24000) == (None, None, 120)


def test_deepgram_non_openai_think_provider_requires_a_model():
    with pytest.raises(ValueError, match="think model is required"):
        _build_realtime_provider(
            "deepgram",
            {"deepgram_api_key": "k", "deepgram_agent_think_provider": "anthropic"},
        )


def test_elevenlabs_builds_with_agent_id():
    provider, voice, model = _build_realtime_provider(
        "elevenlabs", {"elevenlabs_api_key": "k", "elevenlabs_agent_id": "agent_123"}
    )
    assert type(provider).__name__ == "ElevenLabsRealtimeProvider"
    # No per-session voice override — the ElevenLabs agent defines it, and
    # the channel must receive None (the engine maps "" -> None).
    assert voice == ""
    assert model == "agent_123"


def test_xai_builds_with_defaults():
    provider, voice, model = _build_realtime_provider("xai", {"xai_api_key": "k"})
    assert type(provider).__name__ == "XAIRealtimeProvider"
    assert voice == "eve"
    assert model == "grok-2-audio"


def test_xai_custom_model_and_voice():
    _, voice, model = _build_realtime_provider(
        "xai", {"xai_api_key": "k", "xai_model": "grok-3-audio", "xai_voice": "rex"}
    )
    assert voice == "rex"
    assert model == "grok-3-audio"


# -- provider_config (advanced settings) --------------------------------------


def test_xai_defaults_produce_empty_config():
    assert _build_provider_config("xai", {}) == {}


def test_xai_server_vad_tuning_is_parsed():
    config = _build_provider_config(
        "xai",
        {
            "xai_vad_threshold": "0.7",
            "xai_silence_duration_ms": "350",
            "xai_prefix_padding_ms": "250",
        },
    )
    assert config == {"threshold": 0.7, "silence_duration_ms": 350, "prefix_padding_ms": 250}


def test_xai_garbage_tuning_values_are_skipped():
    config = _build_provider_config(
        "xai", {"xai_vad_threshold": "abc", "xai_silence_duration_ms": "12.5"}
    )
    assert config == {}


def test_openai_reasoning_effort_passthrough():
    config = _build_provider_config("openai", {"openai_reasoning_effort": "minimal"})
    assert config["reasoning_effort"] == "minimal"


def test_openai_reasoning_effort_omitted_by_default():
    assert "reasoning_effort" not in _build_provider_config("openai", {})


def test_openai_voice_speed_is_clamped_into_the_api_range():
    assert _build_provider_config("openai", {"openai_voice_speed": "1.2"})["speed"] == 1.2
    assert _build_provider_config("openai", {"openai_voice_speed": "3"})["speed"] == 1.5
    assert _build_provider_config("openai", {"openai_voice_speed": "0.1"})["speed"] == 0.25
    assert "speed" not in _build_provider_config("openai", {})
    assert "speed" not in _build_provider_config("openai", {"openai_voice_speed": "vite"})


def _speak_vendors_supported() -> bool:
    """Whether the installed roomkit carries vendor speak stages (>0.44.0)."""
    from roomkit.providers.deepgram.config import DeepgramAgentConfig

    return "speak_provider" in DeepgramAgentConfig.model_fields


needs_speak_vendors = pytest.mark.skipif(
    not _speak_vendors_supported(),
    reason="installed roomkit predates Deepgram vendor speak stages",
)


def test_deepgram_speak_defaults_to_aura_with_no_override():
    provider, _, _ = _build_realtime_provider("deepgram", {"deepgram_api_key": "k"})
    assert getattr(provider._config, "speak_provider", None) is None
    assert getattr(provider._config, "speak_endpoint", None) is None
    assert provider._config.speak_model == "aura-2-thalia-en"


@pytest.mark.skipif(
    _speak_vendors_supported(), reason="installed roomkit accepts vendor speak stages"
)
def test_deepgram_vendor_tts_on_an_old_roomkit_refuses_legibly():
    with pytest.raises(ValueError, match="newer than 0.44.0"):
        _build_realtime_provider(
            "deepgram",
            {
                "deepgram_api_key": "k",
                "deepgram_agent_speak_provider": "eleven_labs",
                "deepgram_agent_speak_voice": "v",
                "elevenlabs_api_key": "xi",
            },
        )


@needs_speak_vendors
def test_deepgram_elevenlabs_tts_puts_the_voice_in_the_endpoint_url():
    provider, voice_label, _ = _build_realtime_provider(
        "deepgram",
        {
            "deepgram_api_key": "k",
            "deepgram_agent_speak_provider": "eleven_labs",
            "deepgram_agent_speak_voice": "cgSgspJ2msm6clMCkdW9",
            "elevenlabs_api_key": "xi-key",
        },
    )
    cfg = provider._config
    assert cfg.speak_provider == {"type": "eleven_labs", "model_id": "eleven_turbo_v2_5"}
    assert cfg.speak_endpoint == {
        "url": "wss://api.elevenlabs.io/v1/text-to-speech/cgSgspJ2msm6clMCkdW9/multi-stream-input",
        "headers": {"xi-api-key": "xi-key"},
    }
    assert voice_label == "eleven_labs · eleven_turbo_v2_5"


def test_deepgram_elevenlabs_tts_requires_key_and_voice():
    base = {"deepgram_api_key": "k", "deepgram_agent_speak_provider": "eleven_labs"}
    with pytest.raises(ValueError, match="ElevenLabs API key"):
        _build_realtime_provider("deepgram", {**base, "deepgram_agent_speak_voice": "v"})
    with pytest.raises(ValueError, match="voice ID"):
        _build_realtime_provider("deepgram", {**base, "elevenlabs_api_key": "xi"})


@needs_speak_vendors
def test_deepgram_openai_tts_rides_the_speech_endpoint():
    provider, voice_label, _ = _build_realtime_provider(
        "deepgram",
        {
            "deepgram_api_key": "k",
            "deepgram_agent_speak_provider": "open_ai",
            "openai_api_key": "oa-key",
        },
    )
    cfg = provider._config
    assert cfg.speak_provider == {"type": "open_ai", "model": "tts-1", "voice": "alloy"}
    assert cfg.speak_endpoint == {
        "url": "https://api.openai.com/v1/audio/speech",
        "headers": {"authorization": "Bearer oa-key"},
    }
    assert voice_label == "open_ai · alloy"


@needs_speak_vendors
def test_deepgram_aura_speed_is_clamped_and_rides_a_custom_provider():
    provider, _, _ = _build_realtime_provider(
        "deepgram", {"deepgram_api_key": "k", "deepgram_agent_speak_speed": "2.0"}
    )
    assert provider._config.speak_provider == {
        "type": "deepgram",
        "model": "aura-2-thalia-en",
        "speed": 1.5,
    }
    provider, _, _ = _build_realtime_provider(
        "deepgram", {"deepgram_api_key": "k", "deepgram_agent_speak_speed": "vite"}
    )
    assert provider._config.speak_provider is None
