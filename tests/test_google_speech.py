"""Google Gemini STT and TTS in the Voice Channel, on the Gemini key."""

import pytest
import shiboken6

from roomkit_ui.engine_vc import VoiceChannelMixin
from roomkit_ui.features import STT_PROVIDER_FEATURES, TTS_PROVIDER_FEATURES
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.tts import create_tts_provider, is_cached_tts
from roomkit_ui.vc_stt import CLOUD_STT_BUILDERS, build_gemini_stt, stt_needs_turn_vad
from roomkit_ui.widgets.settings.voice_setup import VC_STT_PROVIDERS, VC_TTS_PROVIDERS, VoiceSetup

KEY = {"api_key": "gemini-key"}


def _stt(**settings):
    return build_gemini_stt({**KEY, **settings}, lambda _status: None)


# -- STT: gemini-3.5-transcribe-live ---------------------------------------------------


def test_the_stt_needs_the_gemini_key():
    with pytest.raises(ValueError, match="Google API key"):
        build_gemini_stt({}, lambda _status: None)


def test_the_stt_detects_the_language_unless_the_app_sets_one():
    assert _stt()._config.language_codes == []
    assert _stt(stt_language="fr")._config.language_codes == ["fr"]


def test_the_vocabulary_reaches_the_recogniser_without_blanks():
    config = _stt(gemini_stt_vocabulary="RoomKit, , Tremblay ")._config

    assert config.custom_vocabulary == ["RoomKit", "Tremblay"]


def test_the_stt_streams_and_finds_its_own_turns():
    """Words while the user speaks (semantic barge-in), and no pipeline VAD."""
    assert CLOUD_STT_BUILDERS["gemini"] is build_gemini_stt
    assert _stt().supports_streaming
    assert not stt_needs_turn_vad("gemini")
    assert VoiceChannelMixin._build_vc_vad({"vc_vad_model": "silero"}, "gemini", "cpu") is None


# -- TTS ---------------------------------------------------------------------------------


def test_the_tts_needs_the_gemini_key():
    with pytest.raises(ValueError, match="Google API key"):
        create_tts_provider("gemini", {})


def test_the_tts_defaults_to_the_voice_agent_model():
    tts, rate = create_tts_provider("gemini", KEY)

    assert rate == 24000
    assert tts._config.model == "gemini-3.8-flash-lite-tts"
    assert tts._config.voice == "Kore"
    assert tts._config.style_prompt is None
    assert tts._config.language is None  # taken from the text
    assert not is_cached_tts("gemini")


def test_the_saved_model_voice_and_style_reach_the_tts():
    tts, _ = create_tts_provider(
        "gemini",
        {
            **KEY,
            "gemini_tts_model": "gemini-3.8-flash-tts",
            "gemini_tts_voice": "Puck",
            "gemini_tts_style": "warm and calm",
        },
    )

    assert tts._config.model == "gemini-3.8-flash-tts"
    assert tts._config.voice == "Puck"
    assert tts._config.style_prompt == "warm and calm"


def test_both_need_the_gemini_component():
    assert STT_PROVIDER_FEATURES["gemini"] == "gemini"
    assert TTS_PROVIDER_FEATURES["gemini"] == "gemini"


# -- settings ----------------------------------------------------------------------------


def test_the_settings_offer_gemini_to_listen_and_to_speak(qapp):
    page = VoiceSetup(
        {
            **_DEFAULTS,
            "vc_stt_provider": "gemini",
            "vc_tts_provider": "gemini",
            "gemini_stt_vocabulary": "RoomKit",
            "gemini_tts_voice": "Puck",
            "gemini_tts_style": "warm and calm",
        }
    )
    try:
        google = page._cloud.google
        assert ("Google Gemini", "gemini") in VC_STT_PROVIDERS
        assert ("Google Gemini", "gemini") in VC_TTS_PROVIDERS
        assert not google.vocabulary.isHidden()
        assert not google.voice.isHidden()
        assert google.model.currentText() == "gemini-3.8-flash-lite-tts"
        out = page.get_settings()
        assert out["vc_stt_provider"] == "gemini"
        assert out["vc_tts_provider"] == "gemini"
        assert out["gemini_stt_vocabulary"] == "RoomKit"
        assert out["gemini_tts_model"] == "gemini-3.8-flash-lite-tts"
        assert out["gemini_tts_voice"] == "Puck"
        assert out["gemini_tts_style"] == "warm and calm"
    finally:
        shiboken6.delete(page)


def test_a_voice_typed_by_hand_is_kept(qapp):
    page = VoiceSetup({**_DEFAULTS, "vc_tts_provider": "gemini"})
    try:
        page._cloud.google.voice.setEditText("my-cloned-voice")

        assert page.get_settings()["gemini_tts_voice"] == "my-cloned-voice"
    finally:
        shiboken6.delete(page)


def test_gemini_rows_stay_hidden_for_other_providers(qapp):
    page = VoiceSetup(dict(_DEFAULTS))
    try:
        assert page._cloud.google.vocabulary.isHidden()
        assert page._cloud.google.voice.isHidden()
    finally:
        shiboken6.delete(page)
