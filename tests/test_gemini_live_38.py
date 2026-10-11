"""Gemini 3.8 Live: each option reaches only the models that take it."""

import pytest

from roomkit_ui.realtime_providers import build_provider_config
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.widgets.settings.realtime_section import RealtimeSection

PRE_38 = "gemini-2.5-flash-native-audio-preview-12-2025"
LIVE_38 = "gemini-3.8-live"
THINKING_38 = "gemini-3.8-live-extended-thinking"

EVERYTHING = {
    "gemini_proactive_audio": True,
    "gemini_thinking_level": "high",
    "gemini_language_auto": True,
    "gemini_language_hints": "fr-FR, en-US ,",
    "gemini_custom_vocabulary": "RoomKit, Sylvain",
}


def _config(model: str, **overrides) -> dict:
    return build_provider_config("gemini", {"model": model, **EVERYTHING, **overrides})


# -- provider_config -----------------------------------------------------------


def test_a_pre_38_model_keeps_proactive_audio_and_gets_no_38_fields():
    config = _config(PRE_38)

    assert config["proactive_audio"] is True
    assert "thinking_level" not in config
    assert "transcription" not in config


def test_gemini_38_live_drops_proactive_audio_and_takes_the_transcription_block():
    config = _config(LIVE_38)

    assert "proactive_audio" not in config  # permanent on 3.8, stating it is refused
    assert "thinking_level" not in config  # plain 3.8 takes no thinking config
    assert config["transcription"] == {
        "language_auto": True,
        "language_hints": ["fr-FR", "en-US"],
        "custom_vocabulary": ["RoomKit", "Sylvain"],
    }


def test_extended_thinking_gets_the_level():
    assert _config(THINKING_38)["thinking_level"] == "HIGH"


def test_an_unset_level_leaves_roomkits_low_default():
    assert "thinking_level" not in _config(THINKING_38, gemini_thinking_level="")


def test_an_empty_transcription_block_is_not_sent():
    config = _config(
        LIVE_38,
        gemini_language_auto=False,
        gemini_language_hints="",
        gemini_custom_vocabulary=" , ",
    )
    assert "transcription" not in config


def test_roomkit_builds_the_38_setup_from_it():
    from roomkit.providers.gemini.realtime_config import build_live_config

    setup = build_live_config(THINKING_38, provider_config=_config(THINKING_38))

    assert str(setup.thinking_config.thinking_level).endswith("HIGH")
    heard = setup.input_audio_transcription
    assert heard.language_hints.language_codes == ["fr-FR", "en-US"]
    assert heard.custom_vocabulary == ["RoomKit", "Sylvain"]
    assert heard.language_auto is not None
    assert setup.proactivity is None


# -- settings UI -----------------------------------------------------------------


@pytest.fixture
def section_on(qapp):
    sections: list[RealtimeSection] = []

    def _build(model: str, **overrides) -> RealtimeSection:
        sections.append(RealtimeSection({**_DEFAULTS, "model": model, **overrides}))
        return sections[-1]

    yield _build
    for section in sections:
        section.deleteLater()


def _shown(widget) -> bool:
    return not widget.isHidden()


def test_pre_38_models_keep_their_options_and_hide_the_new_ones(section_on):
    fields = section_on(PRE_38)._gemini_generation

    assert fields._proactive.isEnabled()
    assert fields._affective.isEnabled()
    assert not _shown(fields.thinking_level)
    assert not _shown(fields.custom_vocabulary)


def test_gemini_38_disables_what_it_refuses_and_offers_transcription(section_on):
    section = section_on(LIVE_38)
    fields = section._gemini_generation

    assert not section.gemini_proactive_audio.isEnabled()
    assert "Always on" in section.gemini_proactive_audio.toolTip()
    assert not section.gemini_affective_dialog.isEnabled()
    assert not _shown(fields.thinking_level)
    assert _shown(fields.language_auto)
    assert _shown(fields.custom_vocabulary)


def test_extended_thinking_offers_the_thinking_level(section_on):
    fields = section_on(THINKING_38)._gemini_generation

    assert _shown(fields.thinking_level)


def test_switching_models_updates_the_rows(section_on):
    section = section_on(PRE_38)
    section.gemini_model.setCurrentText(THINKING_38)

    assert _shown(section._gemini_generation.thinking_level)
    assert not section.gemini_proactive_audio.isEnabled()


def test_the_38_settings_round_trip(section_on):
    section = section_on(THINKING_38, **{**EVERYTHING, "gemini_thinking_level": "MEDIUM"})
    out = section.get_settings()

    assert out["gemini_thinking_level"] == "MEDIUM"
    assert out["gemini_language_auto"] is True
    assert out["gemini_language_hints"] == "fr-FR, en-US ,"
    assert out["gemini_custom_vocabulary"] == "RoomKit, Sylvain"
    # A disabled checkbox keeps the value it has for pre-3.8 models.
    assert out["gemini_proactive_audio"] is True
