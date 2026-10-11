"""Guards the settings panel's index alignment and how it saves.

The sidebar labels, the _pages tuple and the hardcoded *_TAB constants are
three parallel structures kept in sync by hand. Inserting a tab shifts every
index below it, and nothing but these assertions would notice.

There is no Save button: closing the dialog, however it is closed, is what
persists the user's changes.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import roomkit_ui.widgets.settings.panel as panel_mod
from roomkit_ui.settings import load_settings, save_settings
from roomkit_ui.widgets.settings.cli_tools_page import _CliToolsPage
from roomkit_ui.widgets.settings.panel import SettingsPanel


@pytest.fixture
def panel(qapp):
    p = SettingsPanel()
    yield p
    p.deleteLater()


def test_every_sidebar_label_has_a_page(panel):
    assert panel._sidebar.count() == len(panel._pages)
    assert panel._stack.count() == len(panel._pages)


def test_the_cli_tools_tab_sits_next_to_mcp_servers(panel):
    labels = [panel._sidebar.item(i).text() for i in range(panel._sidebar.count())]

    assert labels.index("CLI Tools") == labels.index("MCP Servers") + 1


def test_the_refresh_hook_constants_still_point_at_their_own_pages(panel):
    # These fire page-specific refreshes on tab change; a stale index would
    # silently refresh the wrong page.
    assert panel._pages[panel._AUDIO_DEBUG_TAB] is panel._audio_debug
    assert panel._pages[panel._SKILLS_TAB] is panel._skills
    assert panel._pages[panel._AI_TAB] is panel._ai
    assert panel._pages[panel._DICTATION_TAB] is panel._dictation
    assert panel._pages[panel._ATTITUDES_TAB] is panel._attitudes
    assert panel._pages[panel._SPEAKERS_TAB] is panel._speakers


def test_the_cli_tools_page_is_registered_and_contributes_its_slice(panel):
    cli_page = next(p for p in panel._pages if isinstance(p, _CliToolsPage))

    assert "cli_tools" in cli_page.get_settings()


# -- saving on close ---------------------------------------------------------


def test_escape_keeps_the_changes(panel):
    """Esc rejects the dialog without any QCloseEvent — it must still save."""
    panel.show()
    panel._ai.prompt.setPlainText("Answer like a pirate.")

    QTest.keyClick(panel, Qt.Key_Escape)

    assert load_settings()["system_prompt"] == "Answer like a pirate."


@pytest.mark.parametrize("close", [SettingsPanel.reject, SettingsPanel.close])
def test_every_way_out_saves_exactly_once(panel, monkeypatch, close):
    saves: list[dict] = []
    monkeypatch.setattr(panel_mod, "save_settings", saves.append)
    panel.show()

    close(panel)

    assert len(saves) == 1


# -- shared API keys ---------------------------------------------------------


@pytest.fixture
def keyed_panel(qapp):
    """A panel opened over saved keys, each shown on several tabs."""
    save_settings(
        {
            "openai_api_key": "sk-old",
            "api_key": "g-old",
            "deepgram_api_key": "dg-old",
            "elevenlabs_api_key": "el-old",
        }
    )
    p = SettingsPanel()
    p.show()
    yield p
    p.deleteLater()


def _retype(field, text: str) -> None:
    """Replace a field's content the way a user does: select all, type over."""
    field.selectAll()
    if text:
        QTest.keyClicks(field, text)
    else:
        QTest.keyClick(field, Qt.Key_Backspace)


def test_a_key_typed_on_the_dictation_tab_is_the_one_saved(keyed_panel):
    _retype(keyed_panel._dictation.openai_api_key, "sk-new")

    # Every other copy follows the edit at once.
    assert keyed_panel._ai._realtime.openai_api_key.text() == "sk-new"
    assert keyed_panel._ai._cloud.vc_openai_api_key.text() == "sk-new"

    keyed_panel.reject()
    assert load_settings()["openai_api_key"] == "sk-new"


def test_a_cleared_key_stays_cleared(keyed_panel):
    _retype(keyed_panel._ai._cloud.vc_gemini_api_key, "")
    _retype(keyed_panel._dictation.deepgram_api_key, "")

    keyed_panel.reject()

    saved = load_settings()
    assert saved["api_key"] == ""
    assert saved["deepgram_api_key"] == ""


def test_an_elevenlabs_key_edited_for_the_voice_channel_is_saved(keyed_panel):
    _retype(keyed_panel._ai._cloud.elevenlabs_api_key, "el-new")

    keyed_panel.reject()

    assert load_settings()["elevenlabs_api_key"] == "el-new"


def test_untouched_keys_survive_the_save(keyed_panel):
    keyed_panel.reject()

    saved = load_settings()
    assert saved["openai_api_key"] == "sk-old"
    assert saved["api_key"] == "g-old"


# -- voice-channel local models ----------------------------------------------


@pytest.fixture
def all_models_downloaded(monkeypatch):
    """Pretend every local STT and TTS model is on disk."""
    import roomkit_ui.model_manager as model_manager

    monkeypatch.setattr(model_manager, "is_model_downloaded", lambda _id: True)
    monkeypatch.setattr(model_manager, "is_tts_model_downloaded", lambda _id: True)
    return model_manager


def test_vc_models_survive_a_session_in_realtime_mode(qapp, all_models_downloaded):
    stt = all_models_downloaded.STT_MODELS[-1].id
    tts = all_models_downloaded.TTS_MODELS[-1].id
    save_settings({"conversation_mode": "realtime", "vc_stt_model": stt, "vc_tts_model": tts})

    panel = SettingsPanel()  # opens on General: the AI tab is never shown
    panel.reject()
    panel.deleteLater()

    saved = load_settings()
    assert saved["vc_stt_model"] == stt
    assert saved["vc_tts_model"] == tts
