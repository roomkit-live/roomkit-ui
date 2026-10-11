"""Settings navigation uses stable page IDs; every way out persists edits."""

import pytest
import shiboken6
from PySide6.QtCore import QPoint, QSettings, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

import roomkit_ui.widgets.settings.panel as panel_mod
from roomkit_ui.settings import _SECRET_KEYS, load_settings, save_settings
from roomkit_ui.widgets.settings.page_registry import PAGE_SPECS
from roomkit_ui.widgets.settings.panel import SettingsPanel


@pytest.fixture
def open_panel(qapp):
    """Open panels on demand and destroy them when the test ends.

    deleteLater() never runs here — no event loop turns between tests — and
    every panel left alive slows the next ones down: each save restyles
    every widget of the application.
    """
    opened: list[SettingsPanel] = []

    def _open() -> SettingsPanel:
        opened.append(SettingsPanel())
        return opened[-1]

    yield _open
    for p in opened:
        shiboken6.delete(p)


@pytest.fixture
def panel(open_panel):
    return open_panel()


def test_every_sidebar_label_has_a_page(panel):
    keys = [panel._sidebar.item(i).data(Qt.UserRole) for i in range(panel._sidebar.count())]
    assert [key for key in keys if key] == [spec.key for spec in PAGE_SPECS]
    assert panel._stack.count() == len(panel._pages)


def test_integrations_groups_skills_servers_and_cli_tools(panel):
    tabs = panel._integrations.tabs.bar
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "MCP servers",
        "CLI tools",
        "Skills",
    ]
    assert not {"skills", "mcp", "cli_tools"} & panel._page_widgets.keys()


@pytest.mark.parametrize("key", [spec.key for spec in PAGE_SPECS])
def test_each_navigation_destination_opens_its_own_page(panel, key):
    panel._sidebar.select_page(key)
    assert panel._stack.currentWidget() is panel._scrolls[key]
    assert panel._specs[key].title in panel._breadcrumb.text()


def test_group_headings_are_not_selectable(panel):
    headings = [
        panel._sidebar.item(i)
        for i in range(panel._sidebar.count())
        if not panel._sidebar.item(i).data(Qt.UserRole)
    ]
    assert len(headings) == 3
    assert all(not item.flags() & Qt.ItemIsSelectable for item in headings)


def test_keyboard_navigation_skips_group_headings(panel):
    panel.show()
    panel._sidebar.select_page("wakeword")
    QTest.keyClick(panel._sidebar, Qt.Key_Down)
    assert panel._stack.currentWidget() is panel._scrolls["providers"]
    QTest.keyClick(panel._sidebar, Qt.Key_Up)
    assert panel._stack.currentWidget() is panel._scrolls["wakeword"]


def test_general_dictation_link_navigates_without_saving(panel, monkeypatch):
    saves = []
    monkeypatch.setattr(panel_mod, "save_settings", saves.append)
    panel._general.dictation_link.click()
    assert panel._stack.currentWidget() is panel._scrolls["dictation"]
    assert saves == []


def test_settings_can_resize_and_restore_the_chosen_size(open_panel):
    panel = open_panel()
    assert panel.maximumWidth() > panel.minimumWidth()
    assert panel.maximumHeight() > panel.minimumHeight()
    panel.resize(panel.minimumSize())
    chosen = panel.size()
    panel.reject()
    assert QSettings().value("ui/settings_size") == chosen
    reopened = open_panel()
    assert reopened.size() == chosen


def test_oversized_saved_dimensions_fit_the_current_screen(open_panel):
    QSettings().setValue("ui/settings_size", QSize(10000, 10000))
    panel = open_panel()
    available = panel.screen().availableGeometry().size()
    assert panel.width() <= available.width()
    assert panel.height() <= available.height()


def test_general_fits_the_minimum_window_width(panel, qapp):
    panel.show()
    panel.resize(panel.minimumSize())
    qapp.processEvents()
    assert panel._scrolls["general"].horizontalScrollBar().maximum() == 0


def test_theme_choices_apply_immediately_from_the_keyboard(panel, qapp):
    from roomkit_ui.theme import get_stylesheet

    panel.show()
    light = panel._general.theme_picker.options["light"]
    light.setFocus()
    QTest.keyClick(light, Qt.Key_Space)

    assert panel._general.theme_picker.value() == "light"
    assert not panel._general.theme_picker.options["dark"].isChecked()
    assert load_settings()["theme"] == "light"
    assert qapp.styleSheet() == get_stylesheet("light")
    assert panel.isVisible()
    panel._done_button.click()
    assert load_settings()["theme"] == "light"


def test_live_theme_keeps_pending_edits_and_existing_widgets(panel, qapp):
    from PySide6.QtGui import QPalette

    from roomkit_ui.widgets.settings.style import settings_colors

    panel.show()
    prompt = panel._conversation.prompt
    prompt.setPlainText("A pending instruction.")
    panel._providers.fields["openai_api_key"].setText("unsaved-key")
    local_hint = panel._conversation.voice._local._vc_stt_no_models
    for theme in ("light", "dark", "light"):
        panel._general.theme_picker.options[theme].click()
        qapp.processEvents()
        assert panel._conversation.prompt is prompt
        assert prompt.toPlainText() == "A pending instruction."
        assert (
            local_hint.palette().color(QPalette.WindowText).name()
            == settings_colors(theme)["muted"].lower()
        )
        assert load_settings()["system_prompt"] != "A pending instruction."
        assert load_settings()["openai_api_key"] == ""
    panel.reject()
    assert load_settings()["system_prompt"] == "A pending instruction."
    assert load_settings()["openai_api_key"] == "unsaved-key"


def test_search_shortcut_and_escape_leave_pending_edits_untouched(panel, qapp):
    panel.show()
    panel.activateWindow()
    qapp.processEvents()
    panel._conversation.prompt.setPlainText("Pending.")
    QTest.keyClick(panel, Qt.Key_K, Qt.ControlModifier)
    assert panel._search.hasFocus()
    QTest.keyClicks(panel._search, "no-such-setting")
    assert panel._search_results.empty.isVisible()
    QTest.keyClick(panel._search, Qt.Key_Escape)
    assert panel.isVisible()
    assert panel._content_stack.currentWidget() is panel._stack
    assert panel._search.text() == ""
    assert panel._conversation.prompt.toPlainText() == "Pending."
    assert load_settings()["system_prompt"] != "Pending."


@pytest.mark.parametrize("key", [Qt.Key_K, Qt.Key_F])
def test_search_keys_do_not_steal_a_shortcut_being_recorded(panel, qapp, key):
    panel.show()
    panel.activateWindow()
    qapp.processEvents()
    button = panel._general.assistant_hotkey
    button.click()
    assert button.hasFocus()
    QTest.keyClick(button, key, Qt.ControlModifier)
    assert not panel._search.hasFocus()
    assert button.value().endswith("+" + chr(key).lower())


def test_escape_clears_search_even_after_tabbing_to_the_footer(panel):
    panel.show()
    panel._search.setText("theme")
    panel._done_button.setFocus()
    QTest.keyClick(panel._done_button, Qt.Key_Escape)
    assert panel.isVisible()
    assert panel._search.text() == ""


def test_search_opens_personality_and_focuses_instructions(panel, qapp):
    panel.show()
    panel.activateWindow()
    qapp.processEvents()
    panel._search.setText("instructions")
    panel._search.setFocus()
    QTest.keyClick(panel._search, Qt.Key_Down)
    assert panel._search_results.list.hasFocus()
    QTest.keyClick(panel._search_results.list, Qt.Key_Return)
    qapp.processEvents()
    assert panel._stack.currentWidget() is panel._scrolls["conversation"]
    assert panel._conversation.tabs.bar.currentIndex() == 1
    assert panel._conversation.prompt.hasFocus()
    assert panel._conversation.prompt.property("settingsSearchHit") is True


def test_search_finds_credentials_by_french_alias_without_indexing_their_values(panel, qapp):
    panel.show()
    page = panel._providers
    page.fields["azure_speech_api_key"].setText("unique-private-value")
    panel._search.setText("unique-private-value")
    assert panel._search_results.list.count() == 0
    page.search.setText("OpenAI")
    panel._search.setText("Azure clé API")
    panel._search_results.activate_current()
    qapp.processEvents()
    assert page.search.text() == ""
    assert page.fields["azure_speech_api_key"].hasFocus()
    assert page.fields["azure_speech_api_key"].text() == "unique-private-value"


def test_search_never_changes_conversation_mode_to_reveal_a_setting(panel, qapp):
    panel.show()
    panel._search.setText("barge-in")
    panel._search_results.activate_current()
    qapp.processEvents()
    assert panel._conversation.voice.get_settings()["conversation_mode"] == "realtime"
    assert panel._conversation.voice.mode_picker.options["realtime"].hasFocus()
    assert "Select Voice Channel" in panel._search_notice.text()


def test_search_lands_on_claude_thinking_in_the_llm_tab(open_panel, qapp):
    save_settings({"conversation_mode": "voice_channel", "vc_llm_provider": "anthropic"})
    panel = open_panel()
    panel.show()
    panel._search.setText("effort")
    panel._search_results.activate_current()
    qapp.processEvents()
    voice = panel._conversation.voice
    assert voice.pipeline_tabs.bar.currentIndex() == 1
    assert voice._cloud.vc_anthropic_thinking.hasFocus()
    assert panel._search_notice.text() == "Found: Thinking & effort"


def test_search_for_thinking_with_openai_says_where_it_applies(open_panel, qapp):
    save_settings({"conversation_mode": "voice_channel", "vc_llm_provider": "openai"})
    panel = open_panel()
    panel.show()
    panel._search.setText("thinking")
    panel._search_results.activate_current()
    qapp.processEvents()
    assert panel._conversation.voice.get_settings()["vc_llm_provider"] == "openai"
    assert "Claude or Gemini" in panel._search_notice.text()


def test_search_expands_advanced_voice_detection_when_available(open_panel, monkeypatch, qapp):
    import roomkit_ui.model_manager as models

    monkeypatch.setattr(models, "is_vad_model_downloaded", lambda _: True)
    save_settings({"vc_vad_model": models.VAD_MODELS[0].id})
    panel = open_panel()
    panel.show()
    panel._search.setText("VAD threshold")
    panel._search_results.activate_current()
    qapp.processEvents()
    processing = panel._audio.processing
    assert processing.vad_advanced.button.isChecked()
    assert processing.vad_threshold.hasFocus()


def test_all_search_destinations_resolve_to_live_controls(panel):
    from PySide6.QtWidgets import QWidget

    for spec in PAGE_SPECS:
        page = panel._page_widgets[spec.key]
        for target in spec.search:
            for path in (target.control, target.fallback, target.disclosure):
                if path:
                    assert isinstance(panel._resolve(page, path), QWidget), (spec.key, path)
            for path, index in target.tabs:
                tabs = panel._resolve(page, path)
                assert 0 <= index < tabs.bar.count()


def test_disabling_the_shortcut_preserves_its_value(panel):
    panel.show()
    toggle = panel._general.assistant_hotkey_enabled
    shortcut = panel._general.assistant_hotkey
    original = shortcut.value()
    toggle.setFocus()
    QTest.keyClick(toggle, Qt.Key_Space)

    assert not shortcut.isEnabled()
    assert shortcut.value() == original
    panel.reject()
    saved = load_settings()
    assert saved["assistant_hotkey_enabled"] is False
    assert saved["assistant_hotkey"] == original


def test_escape_during_shortcut_capture_does_not_close_settings(panel):
    panel.show()
    shortcut = panel._general.assistant_hotkey
    original = shortcut.value()
    shortcut.click()
    QTest.keyClick(shortcut, Qt.Key_Escape)

    assert panel.isVisible()
    assert shortcut.value() == original
    assert not shortcut._recording


def test_unvisited_audio_and_privacy_pages_still_contribute_to_the_save(open_panel):
    saved = {
        "aec_mode": "speex",
        "denoise": "gtcrn",
        "vad_threshold": "0.6",
        "vad_silence_ms": "800",
        "vad_min_speech_ms": "350",
        "vad_speech_pad_ms": "700",
        "vad_energy_silence_rms": "30",
        "vc_turn_threshold": "0.7",
        "vc_turn_incomplete_wait_ms": "2400",
        "conversation_memory": False,
    }
    save_settings(saved)
    panel = open_panel()
    panel.reject()
    result = load_settings()
    assert {key: result[key] for key in saved} == saved


@pytest.mark.parametrize("key", [spec.key for spec in PAGE_SPECS if spec.refresh])
def test_navigation_refreshes_the_correct_page(panel, monkeypatch, key):
    refreshed = []
    monkeypatch.setattr(
        panel._page_widgets[key], panel._specs[key].refresh, lambda: refreshed.append(key)
    )
    panel._sidebar.select_page(key)
    assert refreshed == [key]


def test_integrations_contributes_each_nested_page_once(panel):
    assert set(panel._integrations.get_settings()) == {
        "cli_tools",
        "mcp_servers",
        "skill_sources",
        "enabled_skills",
    }


# -- saving on close ---------------------------------------------------------


def test_escape_keeps_the_changes(panel):
    """Esc rejects the dialog without any QCloseEvent — it must still save."""
    panel.show()
    panel._conversation.prompt.setPlainText("Answer like a pirate.")

    QTest.keyClick(panel, Qt.Key_Escape)

    assert load_settings()["system_prompt"] == "Answer like a pirate."


@pytest.mark.parametrize(
    "close", [SettingsPanel.reject, SettingsPanel.close, lambda p: p._done_button.click()]
)
def test_every_way_out_saves_exactly_once(panel, monkeypatch, close):
    saves: list[dict] = []
    monkeypatch.setattr(panel_mod, "save_settings", saves.append)
    panel.show()

    close(panel)

    assert len(saves) == 1


# -- centralized API keys ----------------------------------------------------


@pytest.mark.parametrize("key", sorted(_SECRET_KEYS))
def test_provider_keys_can_be_updated_and_removed(open_panel, key):
    save_settings({key: "old-value"})
    panel = open_panel()
    field = panel._providers.fields[key]
    assert field.text() == "old-value"
    field.setText("new-value")
    panel.reject()
    assert load_settings()[key] == "new-value"
    reopened = open_panel()
    reopened._providers.fields[key].clear()
    reopened.reject()
    assert load_settings()[key] == ""


def test_every_setting_has_only_one_owner(panel):
    owners = {}
    for key, page in panel._page_widgets.items():
        if not hasattr(page, "get_settings"):
            continue
        for setting in page.get_settings():
            assert setting not in owners, f"{setting}: {owners.get(setting)} and {key}"
            assert not setting.startswith(("_rt_", "_vc_", "_dict_"))
            owners[setting] = key
    from roomkit_ui.settings import _SECRET_KEYS

    assert all(owners[key] == "providers" for key in _SECRET_KEYS)
    assert owners["recording_enabled"] == "privacy"
    assert owners["conversation_memory"] == "privacy"
    assert owners["input_device"] == "audio"


def test_untouched_keys_survive_a_save(open_panel):
    from roomkit_ui.settings import _SECRET_KEYS

    saved = {key: f"test-{key}" for key in _SECRET_KEYS}
    save_settings(saved)
    open_panel().reject()
    result = load_settings()
    assert {key: result[key] for key in saved} == saved


def test_provider_search_keeps_edits_and_remasks_keys_when_leaving(panel):
    from PySide6.QtWidgets import QLineEdit

    panel.show()
    panel._sidebar.select_page("providers")
    providers = panel._providers
    field = providers.fields["openai_api_key"]
    field.setText("sk-test")
    providers.cards["openai_api_key"].manage.click()
    assert field.isVisible()
    providers._reveals[0].click()
    assert field.echoMode() == QLineEdit.Normal
    providers.search.setText("gemini")
    assert providers.cards["openai_api_key"].isHidden()
    assert not providers.cards["api_key"].isHidden()
    providers.search.clear()
    assert field.text() == "sk-test"
    panel._sidebar.select_page("conversation")
    assert field.echoMode() == QLineEdit.Password
    panel.reject()
    assert load_settings()["openai_api_key"] == "sk-test"


@pytest.mark.parametrize(
    ("page", "link", "destination"),
    [
        ("conversation", "providers_link", "providers"),
        ("dictation", "providers_link", "providers"),
        ("privacy", "files_link", "diagnostics"),
        ("general", "memory_link", "privacy"),
        ("general", "audio_link", "audio"),
        ("privacy", "providers_link", "providers"),
        ("diagnostics", "recordings.recording_link", "privacy"),
    ],
)
def test_context_links_open_the_new_destination_without_saving(
    panel, monkeypatch, page, link, destination
):
    saves = []
    monkeypatch.setattr(panel_mod, "save_settings", saves.append)
    panel._resolve(panel._page_widgets[page], link).click()
    assert panel._stack.currentWidget() is panel._scrolls[destination]
    assert saves == []


def test_context_links_open_personality_and_telemetry_tabs_without_saving(panel, monkeypatch):
    saves = []
    monkeypatch.setattr(panel_mod, "save_settings", saves.append)
    panel._general.personality_link.click()
    assert panel._current_page_key == "conversation"
    assert panel._conversation.tabs.bar.currentIndex() == 1
    panel._privacy.telemetry_link.click()
    assert panel._current_page_key == "diagnostics"
    assert panel._diagnostics.tabs.bar.currentIndex() == 2
    assert saves == []


def test_personality_can_be_viewed_with_enter_without_closing_settings(panel, qapp):
    panel.show()
    panel._general.personality_link.click()
    page = panel._conversation.attitudes
    page._att_list.setCurrentRow(0)
    QTest.keyClick(page._att_list, Qt.Key_Return)
    assert panel.isVisible()
    assert page._name_edit.isReadOnly()
    assert page._text_edit.isReadOnly()
    assert page._text_edit.toPlainText()
    page._show_list()
    page.entries.search.setText(page._att_list.item(0).text())
    assert not page.entries.remove_button.isEnabled()
    assert page.entries.edit_button.isEnabled()


def test_custom_personality_preview_tracks_edits_as_plain_text(panel):
    page = panel._conversation
    page.attitudes._add_attitude()
    page.attitudes._name_edit.setText("Personal")
    page.attitude_combo.setCurrentIndex(page.attitude_combo.findData("Personal"))
    page.attitudes._text_edit.setPlainText("Keep literal <tags> and speak calmly.")
    assert page.personality_preview.text() == "Keep literal <tags> and speak calmly."
    assert page.personality_preview.textFormat() == Qt.PlainText
    page.attitudes._show_list()
    page.attitudes.entries.remove_button.click()
    assert page.attitude_combo.currentData() == ""
    assert page.get_settings()["custom_attitudes"] == "[]"


def test_search_reveals_speaker_tuning_without_changing_its_value(panel, qapp):
    panel.show()
    slider = panel._audio.speakers._threshold_slider
    value = slider.value()
    panel._search.setText("Recognition threshold")
    panel._search_results.activate_current()
    qapp.processEvents()
    assert panel._audio.tabs.bar.currentIndex() == 1
    assert slider.isVisible()
    assert slider.hasFocus()
    assert slider.value() == value


def test_recording_browser_uses_the_unsaved_privacy_folder(panel, tmp_path):
    import wave

    recording = tmp_path / "session.wav"
    with wave.open(str(recording), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 160)
    panel._diagnostics.capture.directory.setText(str(tmp_path / "debug"))
    panel._privacy.recording_enabled.setChecked(True)
    panel._privacy.output_dir.setText(str(tmp_path))
    panel._privacy.files_link.click()
    assert [row.entry.path for row in panel._diagnostics.recordings._rows] == [recording]
    assert load_settings()["recording_output_dir"] == ""
    panel.reject()
    assert load_settings()["recording_output_dir"] == str(tmp_path)


def test_disabling_recording_preserves_its_configuration(open_panel):
    saved = {
        "recording_enabled": True,
        "recording_mode": "inbound_only",
        "recording_channels": "separate",
        "recording_output_dir": "/tmp/roomkit-recording-test",
    }
    save_settings(saved)
    panel = open_panel()
    panel._privacy.recording_enabled.setChecked(False)
    assert not panel._privacy.mode.isEnabled()
    panel.reject()
    result = load_settings()
    assert {key: result[key] for key in saved} == {**saved, "recording_enabled": False}


def test_new_personality_can_be_selected_and_saved_without_leaving_conversation(panel):
    import json

    page = panel._conversation
    page.tabs.bar.setCurrentIndex(1)
    page.attitudes._add_attitude()
    page.attitudes._name_edit.setText("Calm")
    page.attitudes._text_edit.setPlainText("Speak calmly.")
    page.attitude_combo.setCurrentIndex(page.attitude_combo.findData("Calm"))
    page.tabs.bar.setCurrentIndex(0)
    page.tabs.bar.setCurrentIndex(1)
    panel.reject()
    saved = load_settings()
    assert saved["selected_attitude"] == "Calm"
    assert {"name": "Calm", "text": "Speak calmly."} in json.loads(saved["custom_attitudes"])


def test_temporarily_missing_devices_and_models_are_not_cleared(open_panel, monkeypatch):
    monkeypatch.setattr(
        "roomkit_ui.widgets.settings.audio_page._list_audio_devices", lambda: ([], [])
    )
    monkeypatch.setattr("roomkit_ui.model_manager.is_vad_model_downloaded", lambda _: False)
    monkeypatch.setattr("roomkit_ui.model_manager.is_smart_turn_downloaded", lambda: False)
    saved = {
        "input_device": 123,
        "output_device": 456,
        "vc_vad_model": "saved-vad",
        "vc_turn_detector": "smart-turn",
    }
    save_settings(saved)
    panel = open_panel()
    panel._sidebar.select_page("audio")
    assert "unavailable" in panel._audio.processing.input_combo.currentText()
    assert "unavailable" in panel._audio.processing.vad_model.currentText()
    panel.reject()
    result = load_settings()
    assert {key: result[key] for key in saved} == saved


# -- voice-channel local models ----------------------------------------------


@pytest.fixture
def all_models_downloaded(monkeypatch):
    """Pretend every local STT and TTS model is on disk."""
    import roomkit_ui.model_manager as model_manager

    monkeypatch.setattr(model_manager, "is_model_downloaded", lambda _id: True)
    monkeypatch.setattr(model_manager, "is_tts_model_downloaded", lambda _id: True)
    return model_manager


def test_vc_models_survive_a_session_in_realtime_mode(open_panel, all_models_downloaded):
    stt = all_models_downloaded.STT_MODELS[-1].id
    tts = all_models_downloaded.TTS_MODELS[-1].id
    save_settings({"conversation_mode": "realtime", "vc_stt_model": stt, "vc_tts_model": tts})

    open_panel().reject()  # opens on General: Conversation is never shown

    saved = load_settings()
    assert saved["vc_stt_model"] == stt
    assert saved["vc_tts_model"] == tts


# -- revisiting a tab ----------------------------------------------------------


def _leave_and_come_back(panel, tab: str) -> None:
    panel._sidebar.select_page("general")
    panel._sidebar.select_page(tab)


def _pick(combo, data) -> None:
    combo.setCurrentIndex(combo.findData(data))


def test_revisiting_conversation_keeps_the_picked_attitude(open_panel):
    save_settings({"selected_attitude": "Professional"})
    panel = open_panel()
    combo = panel._conversation.attitude_combo
    panel._sidebar.select_page("conversation")

    combo.setCurrentIndex(combo.findText("Concise"))
    _leave_and_come_back(panel, "conversation")
    panel.reject()

    assert load_settings()["selected_attitude"] == "Concise"


def test_revisiting_conversation_keeps_the_picked_vc_models(open_panel, all_models_downloaded):
    stt_models = all_models_downloaded.STT_MODELS
    tts_models = all_models_downloaded.TTS_MODELS
    save_settings(
        {
            "conversation_mode": "voice_channel",
            "vc_stt_model": stt_models[0].id,
            "vc_tts_model": tts_models[0].id,
        }
    )
    panel = open_panel()
    panel._sidebar.select_page("conversation")

    _pick(panel._conversation.voice._local.vc_stt_model, stt_models[1].id)
    _pick(panel._conversation.voice._local.vc_tts_model, tts_models[1].id)
    _leave_and_come_back(panel, "conversation")
    panel.reject()

    saved = load_settings()
    assert saved["vc_stt_model"] == stt_models[1].id
    assert saved["vc_tts_model"] == tts_models[1].id


def test_revisiting_the_dictation_tab_keeps_the_picked_model(open_panel, all_models_downloaded):
    stt_models = all_models_downloaded.STT_MODELS
    save_settings({"stt_provider": "local", "stt_model": stt_models[0].id})
    panel = open_panel()
    panel._sidebar.select_page("dictation")

    _pick(panel._dictation._model_combo, stt_models[1].id)
    _leave_and_come_back(panel, "dictation")
    panel.reject()

    assert load_settings()["stt_model"] == stt_models[1].id


@pytest.mark.parametrize(
    ("query", "tab", "field"),
    [
        ("whisper small", 0, "models.rows.whisper-small"),
        ("gradium component", 1, "components.rows.gradium"),
    ],
)
def test_library_search_clears_filters_and_opens_the_exact_item(panel, qapp, query, tab, field):
    panel.show()
    panel.activateWindow()
    qapp.processEvents()
    library = panel._models
    library.models.search.setText("hidden model")
    library.models.category.setCurrentIndex(2)
    library.models.availability.setCurrentIndex(1)
    library.components.search.setText("hidden component")
    library.components.availability.setCurrentIndex(1)
    panel._search.setText(query)
    panel._search_results.activate_current()
    qapp.processEvents()
    target = panel._resolve(library, field)
    assert panel._stack.currentWidget() is panel._scrolls["models"]
    assert library.tabs.bar.currentIndex() == tab
    assert target.isVisibleTo(library)
    assert target.hasFocus()
    assert target.property("settingsSearchHit") is True


@pytest.mark.parametrize("source", ["conversation", "audio", "dictation"])
def test_model_library_links_keep_pending_edits_and_restore_the_model_tab(panel, source):
    panel._conversation.prompt.setPlainText("Still pending.")
    panel._models.tabs.bar.setCurrentIndex(1)
    panel._models.models.search.setText("no result")
    panel._page_widgets[source].models_link.click()
    assert panel._stack.currentWidget() is panel._scrolls["models"]
    assert panel._models.tabs.bar.currentIndex() == 0
    assert panel._models.models.search.text() == ""
    assert panel._conversation.prompt.toPlainText() == "Still pending."
    assert load_settings()["system_prompt"] != "Still pending."


@pytest.mark.parametrize("tab", [0, 1])
def test_library_fits_the_minimum_window_width(panel, qapp, tab):
    panel.show()
    panel.resize(panel.minimumSize())
    panel._sidebar.select_page("models")
    panel._models.tabs.bar.setCurrentIndex(tab)
    qapp.processEvents()
    assert panel._scrolls["models"].horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize(
    ("query", "tab", "control"),
    [
        ("Recorded audio", 0, "recordings.search"),
        ("Pipeline capture", 1, "capture.stages"),
        ("Capture folder", 1, "capture.directory"),
        ("Telemetry tracing", 2, "telemetry.provider"),
    ],
)
def test_diagnostics_search_opens_the_matching_tab(panel, qapp, query, tab, control):
    panel.show()
    before = panel._diagnostics.get_settings()
    panel._search.setText(query)
    panel._search_results.activate_current()
    qapp.processEvents()
    assert panel._stack.currentWidget() is panel._scrolls["diagnostics"]
    assert panel._diagnostics.tabs.bar.currentIndex() == tab
    assert panel._resolve(panel._diagnostics, control).hasFocus()
    assert panel._diagnostics.get_settings() == before


def test_collector_search_explains_disabled_export_without_enabling_it(panel, qapp):
    panel.show()
    panel._search.setText("Collector endpoint")
    panel._search_results.activate_current()
    qapp.processEvents()
    assert panel._diagnostics.tabs.bar.currentIndex() == 2
    assert panel._diagnostics.telemetry.provider.hasFocus()
    assert panel._diagnostics.get_settings()["telemetry_provider"] == "none"
    assert "Choose OpenTelemetry" in panel._search_notice.text()


def test_privacy_link_returns_to_recordings_after_visiting_telemetry(panel):
    panel._diagnostics.tabs.bar.setCurrentIndex(2)
    panel._diagnostics.recordings.search.setText("no match")
    panel._privacy.files_link.click()
    assert panel._diagnostics.tabs.bar.currentIndex() == 0
    assert panel._diagnostics.recordings.search.text() == ""


def test_license_search_expands_the_license(panel, qapp):
    panel.show()
    panel._search.setText("MIT license")
    panel._search_results.activate_current()
    qapp.processEvents()
    assert panel._about.license.button.isChecked()
    assert panel._about.license.button.hasFocus()


def test_long_recording_names_fit_narrow_settings_and_confirmation(panel, qapp, tmp_path):
    import wave

    filename = "session_4fe7cf2187424989b58a9f067121543c_" * 4 + "05_post_vad_speech_001.wav"
    path = tmp_path / filename
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00" * 160)
    panel._diagnostics.capture.directory.setText(str(tmp_path / "debug"))
    panel._privacy.output_dir.setText(str(tmp_path))
    panel.show()
    panel.resize(panel.minimumSize())
    panel._privacy.files_link.click()
    qapp.processEvents()
    browser = panel._diagnostics.recordings
    assert panel._scrolls["diagnostics"].horizontalScrollBar().maximum() == 0
    browser.delete_shown.click()
    qapp.processEvents()
    assert panel._scrolls["diagnostics"].horizontalScrollBar().maximum() == 0
    assert browser._confirm_filename.accessibleName() == filename
    assert browser._confirm_filename.toolTip() == str(path)
    assert "…" in browser._confirm_filename.text()
    # An actively written recording is retained; its error also fits the page.
    path.write_bytes(path.read_bytes() + b"\x00\x00")
    browser.confirm_delete.click()
    qapp.processEvents()
    assert path.exists()
    assert panel._scrolls["diagnostics"].horizontalScrollBar().maximum() == 0
    assert filename in browser.feedback.toolTip()


def test_conversation_mode_cards_support_clicks_and_arrow_keys(panel, qapp):
    panel.show()
    panel._sidebar.select_page("conversation")
    voice = panel._conversation.voice
    realtime = voice.mode_picker.options["realtime"]
    channel = voice.mode_picker.options["voice_channel"]
    # The whole card is clickable, including the whitespace below the description.
    QTest.mouseClick(channel, Qt.LeftButton, pos=channel.rect().bottomRight() - QPoint(20, 20))
    qapp.processEvents()
    assert voice.get_settings()["conversation_mode"] == "voice_channel"
    assert channel.isChecked() and not realtime.isChecked()
    assert voice._realtime.isHidden()
    assert not voice._vc_section.isHidden()
    channel.setFocus()
    QTest.keyClick(channel, Qt.Key_Left)
    assert voice.get_settings()["conversation_mode"] == "realtime"
    assert realtime.hasFocus()
    assert not voice._realtime.isHidden()
    QTest.keyClick(realtime, Qt.Key_Right)
    assert channel.isChecked() and channel.hasFocus()


def test_pipeline_summary_follows_all_three_provider_choices(panel):
    voice = panel._conversation.voice
    assert [item.text() for item in voice.pipeline.providers] == ["Local", "Anthropic", "Piper"]
    voice.vc_stt_provider.setCurrentIndex(2)
    voice.vc_provider.setCurrentIndex(4)
    voice.vc_tts_provider.setCurrentIndex(4)
    assert [item.text() for item in voice.pipeline.providers] == [
        "Deepgram",
        "llama.cpp",
        "ElevenLabs",
    ]


def test_mode_navigation_and_live_theme_preserve_pending_conversation_edits(panel, qapp):
    from roomkit_ui.theme_live import apply_theme

    panel.show()
    panel._sidebar.select_page("conversation")
    voice = panel._conversation.voice
    voice._cloud.vc_openai_model.setCurrentText("custom-model")
    voice._realtime.openai_voice.setCurrentIndex(1)
    voice.vc_provider.setCurrentIndex(1)
    voice.mode_picker.options["voice_channel"].click()
    before = voice.get_settings()
    for theme in ("light", "dark"):
        voice.mode_picker.options["realtime"].click()
        apply_theme(theme)
        panel._conversation.tabs.bar.setCurrentIndex(1)
        panel._conversation.tabs.bar.setCurrentIndex(0)
        voice.mode_picker.options["voice_channel"].click()
        qapp.processEvents()
        assert voice.get_settings() == before
    # Appearance is the only setting saved immediately.
    assert load_settings()["conversation_mode"] == "realtime"
    panel.reject()
    assert load_settings()["conversation_mode"] == "voice_channel"
    assert load_settings()["vc_openai_model"] == "custom-model"


def test_conversation_cards_fit_minimum_window_width(panel, qapp):
    panel.show()
    panel.resize(panel.minimumSize())
    panel._sidebar.select_page("conversation")
    voice = panel._conversation.voice
    for mode in ("realtime", "voice_channel"):
        voice.mode_picker.set_value(mode)
        qapp.processEvents()
        assert panel._scrolls["conversation"].horizontalScrollBar().maximum() == 0
        for card in voice.mode_picker.options.values():
            assert card.height() >= 172
            for copy in card.findChildren(QLabel):
                assert card.rect().contains(copy.geometry())
    assert not hasattr(voice, "mode_combo")


def test_mode_cards_preserve_missing_local_models_until_replaced(open_panel, monkeypatch):
    import roomkit_ui.model_manager as models

    monkeypatch.setattr(models, "is_model_downloaded", lambda _id: False)
    monkeypatch.setattr(models, "is_tts_model_downloaded", lambda _id: False)
    save_settings({"vc_stt_model": "missing-stt", "vc_tts_model": "missing-tts"})
    panel = open_panel()
    voice = panel._conversation.voice
    for mode in ("voice_channel", "realtime", "voice_channel"):
        voice.mode_picker.set_value(mode)
        assert voice.get_settings()["vc_stt_model"] == "missing-stt"
        assert voice.get_settings()["vc_tts_model"] == "missing-tts"
    assert "not downloaded" in voice._local.vc_stt_model.currentText()
    assert "not downloaded" in voice._local.vc_tts_model.currentText()
    assert not voice._local._vc_stt_no_models.isHidden()
    assert not voice._local._vc_tts_no_models.isHidden()
    # Availability can change while Settings is open; an explicit replacement clears the hint.
    monkeypatch.setattr(models, "is_model_downloaded", lambda _id: True)
    voice.refresh_vc_model_combos()
    voice._local.vc_stt_model.setCurrentIndex(0)
    assert voice._local._vc_stt_no_models.isHidden()


def test_provider_management_keeps_one_editor_open_and_masks_collapsed_keys(panel):
    from PySide6.QtWidgets import QLineEdit

    panel.show()
    panel._navigate("providers")
    page = panel._providers
    assert all(not field.isVisible() for field in page.fields.values())
    page.cards["openai_api_key"].manage.click()
    page.fields["openai_api_key"].setText("pending-secret")
    page._reveals[0].click()
    page.cards["api_key"].manage.click()
    assert page.fields["api_key"].isVisible()
    assert not page.fields["openai_api_key"].isVisible()
    assert page.fields["openai_api_key"].echoMode() == QLineEdit.Password
    assert page.get_settings()["openai_api_key"] == "pending-secret"
    assert load_settings()["openai_api_key"] == ""
    page.cards["api_key"].manage.click()
    assert all(not field.isVisible() for field in page.fields.values())


def test_provider_component_and_key_status_are_distinct(panel, monkeypatch):
    import roomkit_ui.widgets.settings.providers_page as providers_mod

    page = panel._providers
    monkeypatch.setattr(providers_mod, "unavailable_reason", lambda _: None)
    page.refresh()
    assert page.cards["api_key"].status.text() == "No key"
    page.fields["api_key"].setText("pending-key")
    assert page.cards["api_key"].status.text() == "Key added"
    monkeypatch.setattr(providers_mod, "unavailable_reason", lambda _: "Component missing")
    page.refresh()
    assert page.cards["api_key"].status.text() == "Component needed"
    assert "Key added" in page.cards["api_key"].status.toolTip()
    assert "not tested" in page.cards["api_key"].status.toolTip()
