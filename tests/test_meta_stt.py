"""Meta Muse Voice Transcribe: built from settings, the key kept in the keyring."""

import pytest
import shiboken6
from PySide6.QtCore import QSettings
from roomkit.voice.stt.meta import SUPPORTED_LANGUAGES

import roomkit_ui.settings as settings_mod
from roomkit_ui.constants import STT_LANGUAGES
from roomkit_ui.engine_vc import VoiceChannelMixin
from roomkit_ui.features import STT_PROVIDER_FEATURES
from roomkit_ui.secret_store import SecretStore
from roomkit_ui.settings import _DEFAULTS, load_settings, save_settings
from roomkit_ui.vc_stt import _META_LANGUAGES, CLOUD_STT_BUILDERS, build_meta_stt
from roomkit_ui.widgets.settings.ai_page import VC_STT_PROVIDERS, _AIPage


def _config(**settings):
    return build_meta_stt({"meta_api_key": "k", **settings}, lambda _status: None)._config


def test_the_stt_needs_its_key():
    with pytest.raises(ValueError, match="Meta API key"):
        build_meta_stt({"meta_api_key": "  "}, lambda _status: None)


def test_the_model_ends_turns_and_takes_any_language_by_default():
    config = _config()

    assert config.model == "muse-voice-transcribe-1.0"
    assert config.mode == "ENDPOINTING"
    assert config.language_bias == []
    assert config.keywords == []


def test_the_app_language_becomes_the_name_muse_takes():
    assert _config(stt_language="fr").language_bias == ["French"]
    assert _config(stt_language="zh").language_bias == ["Mandarin Chinese"]


def test_a_language_muse_does_not_transcribe_is_refused_by_its_name():
    with pytest.raises(ValueError, match="does not transcribe Russian"):
        _config(stt_language="ru")


def test_every_language_muse_lists_has_its_code():
    # roomkit's list is what the service takes; a misspelt name is ignored silently.
    assert set(_META_LANGUAGES.values()) == SUPPORTED_LANGUAGES
    offered = {code for _label, code in STT_LANGUAGES if code}
    assert offered - set(_META_LANGUAGES) == {"ru"}


def test_keywords_are_split_on_commas_and_blanks_dropped():
    config = _config(meta_stt_keywords=" RoomKit, , Tremblay ,")

    assert config.keywords == ["RoomKit", "Tremblay"]


def test_the_session_builds_muse_without_a_pipeline_vad():
    assert CLOUD_STT_BUILDERS["meta"] is build_meta_stt
    assert STT_PROVIDER_FEATURES["meta"] == "meta-stt"
    # The model finds the turns: a VAD would end them for it.
    assert VoiceChannelMixin._build_vc_vad({"vc_vad_model": "x"}, "meta", "cpu") is None


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


def test_the_meta_key_lives_in_the_keyring_not_in_qsettings(monkeypatch):
    store = SecretStore(service="svc", namespace="ns", keyring_backend=_FakeKeyring())
    monkeypatch.setattr(settings_mod, "get_secret_store", lambda: store)

    save_settings({"meta_api_key": "meta-secret", "meta_stt_keywords": "RoomKit"})

    assert QSettings().value("room/meta_api_key", None) is None
    assert store.get_secret("settings:meta_api_key") == "meta-secret"
    out = load_settings()
    assert out["meta_api_key"] == "meta-secret"
    assert out["meta_stt_keywords"] == "RoomKit"


def test_the_settings_page_offers_muse_with_its_fields(qapp):
    page = _AIPage(
        {
            **_DEFAULTS,
            "vc_stt_provider": "meta",
            "meta_api_key": "k",
            "meta_stt_keywords": "RoomKit",
        }
    )
    try:
        meta = page._cloud.meta
        assert ("Meta Muse Voice Transcribe", "meta") in VC_STT_PROVIDERS
        assert not meta.api_key.isHidden()
        assert not meta.keywords.isHidden()
        out = page.get_settings()
        assert out["vc_stt_provider"] == "meta"
        assert out["meta_api_key"] == "k"
        assert out["meta_stt_keywords"] == "RoomKit"
    finally:
        shiboken6.delete(page)


def test_meta_rows_stay_hidden_for_other_providers(qapp):
    page = _AIPage(dict(_DEFAULTS))
    try:
        assert page._cloud.meta.api_key.isHidden()
        assert page._cloud.meta.keywords.isHidden()
    finally:
        shiboken6.delete(page)
