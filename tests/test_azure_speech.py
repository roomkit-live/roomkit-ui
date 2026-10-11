"""Azure MAI-Transcribe and MAI-Voice: built from settings, the key kept in the keyring."""

import pytest
import shiboken6
from PySide6.QtCore import QSettings

import roomkit_ui.settings as settings_mod
from roomkit_ui.engine_vc import VoiceChannelMixin
from roomkit_ui.engine_vc_helpers import build_azure_mai_stt, build_turn_vad, stt_needs_turn_vad
from roomkit_ui.secret_store import SecretStore
from roomkit_ui.settings import _DEFAULTS, load_settings, save_settings
from roomkit_ui.tts import azure as azure_tts
from roomkit_ui.widgets.settings.ai_page import VC_STT_PROVIDERS, VC_TTS_PROVIDERS, _AIPage

ENDPOINT = "https://acme.services.ai.azure.com"
STT = {"azure_speech_api_key": "k", "azure_mai_endpoint": ENDPOINT}
TTS = {"azure_speech_api_key": "k", "azure_speech_region": "swedencentral"}


def _stt(**overrides):
    return build_azure_mai_stt({**STT, **overrides}, lambda _status: None)


# -- MAI-Transcribe -----------------------------------------------------------------


def test_the_stt_needs_its_key_and_endpoint():
    with pytest.raises(ValueError, match="key and endpoint"):
        build_azure_mai_stt({"azure_speech_api_key": "k"}, lambda _status: None)
    with pytest.raises(ValueError, match="key and endpoint"):
        build_azure_mai_stt({"azure_mai_endpoint": ENDPOINT}, lambda _status: None)


def test_the_stt_defaults_to_roomkits_deployment_and_detects_the_language():
    config = _stt()._config

    assert config.endpoint == ENDPOINT
    assert config.deployment == "MAI-Transcribe-2-Streaming"
    assert config.language is None  # detected utterance by utterance


def test_the_app_language_and_a_named_deployment_reach_the_stt():
    config = _stt(stt_language="fr", azure_mai_deployment="my-mai")._config

    assert config.language == "fr"
    assert config.deployment == "my-mai"


def test_a_language_mai_does_not_take_is_refused_legibly():
    with pytest.raises(ValueError, match="does not support language"):
        _stt(stt_language="tlh")


# -- the VAD a turnless STT needs -----------------------------------------------------


def test_only_the_turnless_stt_asks_for_a_turn_vad():
    assert stt_needs_turn_vad("azure_mai")
    assert not stt_needs_turn_vad("local")
    assert not stt_needs_turn_vad("deepgram")


def test_without_a_vad_model_an_energy_vad_ends_turns_after_800ms():
    vad = VoiceChannelMixin._build_vc_vad({**STT, "vc_vad_model": ""}, "azure_mai", "cpu")

    assert type(vad).__name__ == "EnergyVADProvider"
    assert vad._silence_threshold_ms == 800


def test_the_users_silence_setting_wins_and_garbage_falls_back():
    assert build_turn_vad({"vad_silence_ms": "600"}, "cpu")._silence_threshold_ms == 600
    assert build_turn_vad({"vad_silence_ms": "soon"}, "cpu")._silence_threshold_ms == 800


def test_cloud_stts_that_find_turns_still_get_no_vad():
    assert VoiceChannelMixin._build_vc_vad({"vc_vad_model": ""}, "deepgram", "cpu") is None


# -- MAI-Voice ------------------------------------------------------------------------


def test_the_tts_needs_its_key_and_region():
    with pytest.raises(ValueError, match="key and region"):
        azure_tts.create({"azure_speech_api_key": "k"})


def test_the_tts_defaults_to_mai_voice_flash_at_the_voices_own_pace():
    tts, rate = azure_tts.create(TTS)

    assert rate == 24000
    assert tts._config.voice == "en-US-Harper:MAI-Voice-2.1-Flash"
    assert tts._config.rate is None
    assert tts._config.sample_rate == 24000


def test_a_french_voice_and_a_rate_reach_the_tts():
    tts, _ = azure_tts.create(
        {**TTS, "azure_tts_voice": "fr-FR-Soleil:MAI-Voice-2.1-Flash", "azure_tts_rate": "+15%"}
    )

    assert tts._config.voice == "fr-FR-Soleil:MAI-Voice-2.1-Flash"
    assert tts._config.rate == "+15%"


# -- settings -------------------------------------------------------------------------


class _FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


def test_the_azure_key_lives_in_the_keyring_not_in_qsettings(monkeypatch):
    store = SecretStore(service="svc", namespace="ns", keyring_backend=_FakeKeyring())
    monkeypatch.setattr(settings_mod, "get_secret_store", lambda: store)

    save_settings({"azure_speech_api_key": "azure-secret", "azure_speech_region": "eastus"})

    assert QSettings().value("room/azure_speech_api_key", None) is None
    assert store.get_secret("settings:azure_speech_api_key") == "azure-secret"
    out = load_settings()
    assert out["azure_speech_api_key"] == "azure-secret"
    assert out["azure_speech_region"] == "eastus"


def test_the_settings_page_offers_azure_on_both_pages(qapp):
    page = _AIPage(
        {
            **_DEFAULTS,
            "vc_stt_provider": "azure_mai",
            "vc_tts_provider": "azure",
            "azure_speech_api_key": "k",
            "azure_mai_endpoint": ENDPOINT,
            "azure_speech_region": "swedencentral",
            "azure_tts_rate": "+15%",
        }
    )
    try:
        azure = page._cloud.azure
        assert ("Azure MAI-Transcribe", "azure_mai") in VC_STT_PROVIDERS
        assert ("Azure MAI-Voice", "azure") in VC_TTS_PROVIDERS
        assert not azure.endpoint.isHidden()
        assert not azure.region.isHidden()
        # One key, one copy per page, mirrored by the dialog.
        assert page.api_key_fields()["azure_speech_api_key"] == [azure.stt_key, azure.tts_key]
        out = page.get_settings()
        assert out["azure_speech_api_key"] == "k"
        assert out["azure_mai_endpoint"] == ENDPOINT
        assert out["azure_speech_region"] == "swedencentral"
        assert out["azure_tts_rate"] == "+15%"
    finally:
        shiboken6.delete(page)


def test_azure_rows_stay_hidden_for_other_providers(qapp):
    page = _AIPage(dict(_DEFAULTS))
    try:
        assert page._cloud.azure.endpoint.isHidden()
        assert page._cloud.azure.voice.isHidden()
    finally:
        shiboken6.delete(page)
