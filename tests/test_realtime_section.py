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
