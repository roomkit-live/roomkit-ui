"""The details inventory follows resolved backends, including SDK defaults."""

import importlib
import json
from types import SimpleNamespace

import pytest
from roomkit.providers.ai.mock import MockAIProvider

from roomkit_ui.realtime_providers import build_provider_config, build_realtime_provider
from roomkit_ui.session_models import realtime_models, voice_channel_models
from roomkit_ui.vc_agent import VCAgent, build_vc_agent
from roomkit_ui.vc_stt import CLOUD_STT_BUILDERS


def _vc(settings, *, stt=None, llm=None, tts=None, agent=None):
    return voice_channel_models(
        settings,
        stt=stt or SimpleNamespace(_config=SimpleNamespace(language="fr")),
        stt_provider=settings.get("vc_stt_provider", "local"),
        llm=llm or SimpleNamespace(model_name="conversation-model"),
        tts=tts or SimpleNamespace(default_voice="0"),
        agent=agent or VCAgent(),
    )


@pytest.mark.parametrize("name", CLOUD_STT_BUILDERS)
def test_cloud_stt_reports_the_factory_config_with_its_defaults(name):
    settings = {
        "vc_stt_provider": name,
        "stt_language": "fr",
        "gradium_api_key": "secret-test",
        "deepgram_api_key": "secret-test",
        "azure_speech_api_key": "secret-test",
        "azure_mai_endpoint": "https://test.invalid",
        "meta_api_key": "secret-test",
        "api_key": "secret-test",
        "vc_stt_model": "unused-local-model",
    }
    provider = CLOUD_STT_BUILDERS[name](settings, lambda _: None)
    part = _vc(settings, stt=provider)[0]
    assert part["provider"] == name
    config = provider._config
    expected = next(
        getattr(config, field)
        for field in ("model", "model_name", "deployment")
        if hasattr(config, field)
    )
    assert part["model"] == expected
    assert "fr" in part["description"] or "French" in part["description"]
    assert "secret-test" not in json.dumps(part)
    assert "unused-local-model" not in json.dumps(part)


@pytest.mark.parametrize(
    ("name", "module", "config_type", "provider_type", "expected"),
    [
        ("gradium", "gradium", "GradiumTTSConfig", "GradiumTTSProvider", "default"),
        ("elevenlabs", "elevenlabs", "ElevenLabsConfig", "ElevenLabsTTSProvider", "custom-model"),
        ("gemini", "gemini", "GeminiTTSConfig", "GeminiTTSProvider", "gemini-3.8-flash-tts"),
        (
            "azure",
            "azure_speech",
            "AzureSpeechTTSConfig",
            "AzureSpeechTTSProvider",
            "MAI-Voice-2.1-Flash",
        ),
        ("pocket", "pocket", "PocketTTSConfig", "PocketTTSProvider", "english"),
        ("qwen3", "qwen3", "Qwen3TTSConfig", "Qwen3TTSProvider", "Qwen/Qwen3-TTS-12Hz-1.7B-Base"),
        (
            "neutts",
            "neutts",
            "NeuTTSConfig",
            "NeuTTSProvider",
            "neuphonic/neutts-nano-french-q8-gguf",
        ),
    ],
)
def test_tts_models_and_voices_from_resolved_sdk_configs(
    name, module, config_type, provider_type, expected
):
    sdk = importlib.import_module(f"roomkit.voice.tts.{module}")
    kwargs = (
        {"api_key": "secret-test"} if name in {"gradium", "elevenlabs", "gemini", "azure"} else {}
    )
    if name == "elevenlabs":
        kwargs.update(model_id="custom-model", voice_id="custom-voice")
    if name == "azure":
        kwargs.update(region="eastus", voice="en-US-Harper:MAI-Voice-2.1-Flash")
    # Reading metadata must not load local weights or create vendor clients.
    provider = object.__new__(getattr(sdk, provider_type))
    provider._config = getattr(sdk, config_type)(**kwargs)
    part = _vc({"vc_tts_provider": name, "vc_tts_model": "unused-local-model"}, tts=provider)[2]
    assert part["model"] == expected
    assert "Voice · " in part["description"]
    assert "secret-test" not in json.dumps(part)
    assert "unused-local-model" not in json.dumps(part)
    if name == "neutts":
        assert "neuphonic/neucodec" in part["description"]


def test_local_models_use_catalogue_ids_and_a_cloned_voice_hides_its_path():
    models = _vc({"vc_stt_model": "whisper-small", "vc_tts_model": "piper-fr-siwis"})
    assert models[0]["model"] == "whisper-small"
    assert models[2]["model"] == "piper-fr-siwis"
    assert models[3]["model"] == "Always answer"
    tts = SimpleNamespace(
        default_voice="default",
        _config=SimpleNamespace(
            language="french", voices={"default": "/private/voice-clips/voice.wav"}
        ),
    )
    part = _vc({"vc_tts_provider": "pocket"}, tts=tts)[2]
    assert part["model"] == "french"
    assert "Cloned · voice.wav" in part["description"]
    assert "/private" not in json.dumps(part)


@pytest.mark.parametrize("policy", ["openai", "jev", "llm"])
async def test_active_decision_model_and_thinker_are_reported(policy):
    settings = {
        "vc_speak_policy": policy,
        "openai_api_key": "secret-test",
        "typesafe_api_key": "secret-test",
        "vc_llm_provider": "gemini",
        "vc_thinker": True,
    }
    provider = MockAIProvider(response_schema=True)
    agent = build_vc_agent(settings, provider, lambda _: None)
    try:
        parts = _vc(settings, agent=agent, llm=provider)
        assert parts[3]["role"] == "Speaking decision"
        assert parts[3]["model"] != "Model not reported"
        if policy == "openai":
            from roomkit.classifiers.openai import DEFAULT_MODEL

            assert parts[3]["model"] == DEFAULT_MODEL
        elif policy == "llm":
            assert parts[3]["model"] == provider.model_name
            assert parts[3]["provider"] == "gemini"
        else:
            assert parts[3]["model"] == agent._closables[0]._client._config.default_model
        assert parts[4]["role"] == "Think while listening"
        assert parts[4]["model"] == parts[1]["model"]
        assert "secret-test" not in json.dumps(parts)
    finally:
        await agent.close()


def test_requested_but_unavailable_decision_and_thinker_are_not_reported_as_active():
    settings = {"vc_speak_policy": "openai", "openai_api_key": "", "vc_thinker": True}
    agent = build_vc_agent(settings, MockAIProvider(), lambda _: None)
    parts = _vc(settings, agent=agent)
    assert parts[3]["model"] == "Always answer"
    assert parts[4]["model"] == "Inactive"
    assert "no API key" in agent.summary[0]["description"]


def _realtime(name, **options):
    settings = {
        "api_key": "secret-test",
        "openai_api_key": "secret-test",
        "deepgram_api_key": "secret-test",
        "elevenlabs_api_key": "secret-test",
        "xai_api_key": "secret-test",
        "elevenlabs_agent_id": "agent-test",
        **options,
    }
    provider, voice, model = build_realtime_provider(name, settings)
    parts = realtime_models(
        name,
        provider,
        model=model,
        voice=voice,
        settings=settings,
        provider_config=build_provider_config(name, settings),
    )
    assert "secret-test" not in json.dumps(parts)
    return provider, parts


@pytest.mark.parametrize("name", ["gemini", "openai", "xai", "openai_live"])
def test_realtime_integrated_audio_model_and_voice(name):
    provider, parts = _realtime(name)
    assert parts[0]["model"] == provider.model_name
    assert "Voice · " in parts[0]["description"]
    assert parts[-1]["role"] == "Speaking decision"
    if name == "openai_live":
        assert parts[1]["model"] == provider.delegation.model
        assert provider.delegation.reasoning_effort in parts[1]["description"]
    elif name == "openai":
        config = provider._build_session_config(
            system_prompt=None,
            voice=None,
            tools=None,
            temperature=None,
            input_sample_rate=24000,
            output_sample_rate=24000,
            server_vad=True,
            pc={},
        )
        assert parts[1]["model"] == config["audio"]["input"]["transcription"]["model"]


@pytest.mark.parametrize(
    ("vendor", "model", "voice"),
    [
        ("", "aura-2-thalia-en", ""),
        ("open_ai", "tts-1", "alloy"),
        ("eleven_labs", "eleven_turbo_v2_5", "custom-voice"),
    ],
)
def test_deepgram_reports_derived_stt_llm_and_vendor_tts(vendor, model, voice):
    _, parts = _realtime(
        "deepgram",
        deepgram_agent_listen_language="fr",
        deepgram_agent_think_provider="anthropic",
        deepgram_agent_think_model="claude-test",
        deepgram_agent_speak_provider=vendor,
        deepgram_agent_speak_voice=voice,
    )
    assert parts[0]["model"] == "nova-2"
    assert parts[1]["provider"] == "anthropic"
    assert parts[1]["model"] == "claude-test"
    assert parts[2]["provider"] == (vendor or "deepgram")
    assert parts[2]["model"] == model
    if voice:
        assert voice in parts[2]["description"]


def test_remote_agent_does_not_invent_hidden_models():
    _, parts = _realtime("elevenlabs")
    assert parts[0]["role"] == "Realtime agent"
    assert parts[0]["model"] == "agent-test"
    assert "STT, LLM, TTS and voice" in parts[0]["description"]
    assert "not reported" in parts[0]["description"]
