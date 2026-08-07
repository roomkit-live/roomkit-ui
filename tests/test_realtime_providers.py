"""Realtime provider construction dispatch (engine_realtime helpers)."""

import pytest

from roomkit_ui.engine_realtime import (
    _build_realtime_provider,
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
