"""RealtimeSection voice combos are fed by roomkit's offline catalogs."""

import pytest

from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.widgets.settings.realtime_section import RealtimeSection


@pytest.fixture
def section(qapp):
    s = RealtimeSection(dict(_DEFAULTS))
    yield s
    s.deleteLater()


def _ids(combo):
    return [combo.itemData(i) for i in range(combo.count())]


def test_voice_combos_use_the_roomkit_catalogs(section):
    # Way beyond the 5-entry fallback lists once the catalogs load.
    assert section.gemini_voice.count() >= 20
    assert section.deepgram_voice.count() >= 50
    # The realtime-exclusive OpenAI voices only exist in the catalog.
    assert "marin" in _ids(section.openai_voice)


def test_deprecated_aura1_voices_are_filtered(section):
    aura1 = [
        v
        for v in _ids(section.deepgram_voice)
        if str(v).startswith("aura-") and "-2-" not in str(v)
    ]
    assert aura1 == []


def test_selected_voice_ids_round_trip(section):
    s = section.get_settings()
    assert s["voice"] == "Aoede"
    assert s["openai_voice"] == "alloy"
    assert s["deepgram_agent_voice"] == "aura-2-thalia-en"
    assert s["xai_voice"] == "eve"


def test_typed_deepgram_voice_id_wins(section):
    section.deepgram_voice.setCurrentText("aura-2-luna-en")
    assert section.get_settings()["deepgram_agent_voice"] == "aura-2-luna-en"


# -- model dropdowns ---------------------------------------------------------


def test_sts_model_combos_carry_the_documented_lineups(section):
    gemini_models = [section.gemini_model.itemText(i) for i in range(section.gemini_model.count())]
    openai_models = [section.openai_model.itemText(i) for i in range(section.openai_model.count())]
    assert "gemini-3.1-flash-live-preview" in gemini_models
    assert "gpt-realtime-2.1-mini" in openai_models


def test_sts_model_combos_are_fixed_dropdowns(section):
    assert not section.gemini_model.isEditable()
    assert not section.openai_model.isEditable()
    assert not section.xai_model.isEditable()


def test_saved_model_outside_the_lineup_stays_selectable(qapp):
    settings = dict(_DEFAULTS)
    settings["openai_model"] = "gpt-realtime-pinned-snapshot"
    s = RealtimeSection(settings)
    try:
        assert s.openai_model.currentText() == "gpt-realtime-pinned-snapshot"
        assert s.get_settings()["openai_model"] == "gpt-realtime-pinned-snapshot"
    finally:
        s.deleteLater()


def test_think_model_suggestions_come_from_the_roomkit_catalog(section):
    models = [
        section.deepgram_think_model.itemText(i)
        for i in range(section.deepgram_think_model.count())
    ]
    # Default think provider is open_ai → OpenAI chat catalog (~21 entries).
    assert len(models) >= 15
    assert any(m.startswith("gpt-") for m in models)
    # Saved default is empty — the combo must not silently adopt an entry.
    assert section.deepgram_think_model.currentText() == ""


def test_switching_think_provider_swaps_the_catalog(section):
    # index 1 = Anthropic (see DEEPGRAM_THINK_PROVIDERS)
    section.deepgram_think_provider.setCurrentIndex(1)
    models = [
        section.deepgram_think_model.itemText(i)
        for i in range(section.deepgram_think_model.count())
    ]
    assert any(m.startswith("claude-") for m in models)
    assert not any(m.startswith("gpt-") for m in models)
    # The old vendor's model id was cleared, not carried over.
    assert section.deepgram_think_model.currentText() == ""


def test_saved_think_model_survives_construction(qapp):
    settings = dict(_DEFAULTS)
    settings["deepgram_agent_think_provider"] = "google"
    settings["deepgram_agent_think_model"] = "gemini-2.5-flash"
    s = RealtimeSection(settings)
    try:
        assert s.get_settings()["deepgram_agent_think_model"] == "gemini-2.5-flash"
        assert s.get_settings()["deepgram_agent_think_provider"] == "google"
    finally:
        s.deleteLater()


def test_sts_model_options_fall_back_until_the_catalog_ships():
    from roomkit_ui.widgets.settings.realtime_section import _sts_model_options

    # Unknown module (roomkit 0.43 has no realtime_models) → the local lineup.
    assert _sts_model_options("roomkit.providers.gemini.realtime_models_nope", ["a", "b"]) == [
        "a",
        "b",
    ]


def test_deepgram_language_and_half_duplex_round_trip(qapp):
    settings = dict(_DEFAULTS)
    settings["deepgram_agent_listen_language"] = "fr"
    settings["deepgram_agent_half_duplex"] = False
    settings["deepgram_agent_listen_model"] = "flux-general-en"
    s = RealtimeSection(settings)
    try:
        out = s.get_settings()
        assert out["deepgram_agent_listen_language"] == "fr"
        assert out["deepgram_agent_half_duplex"] is False
        assert out["deepgram_agent_listen_model"] == "flux-general-en"
    finally:
        s.deleteLater()


def test_deepgram_defaults_half_duplex_off_and_auto_model(section):
    out = section.get_settings()
    assert out["deepgram_agent_half_duplex"] is False
    assert out["deepgram_agent_listen_model"] == ""  # auto
    assert out["deepgram_agent_listen_language"] == ""  # English default
