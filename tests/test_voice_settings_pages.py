"""Voice settings retain choices, explain prerequisites and share download lifetime."""

import asyncio
from types import SimpleNamespace

import pytest
import shiboken6
from PySide6.QtWidgets import QComboBox

from roomkit_ui import model_catalog, model_manager
from roomkit_ui.settings import load_settings, save_settings
from roomkit_ui.theme_live import apply_theme
from roomkit_ui.wakeword import encoder_download
from roomkit_ui.widgets.settings import wakeword_page
from roomkit_ui.widgets.settings.dictation_page import _DictationPage
from roomkit_ui.widgets.settings.model_jobs import ModelDownloads
from roomkit_ui.widgets.settings.model_library import wakeword_encoder_model
from roomkit_ui.widgets.settings.models_page import _ModelsPage
from roomkit_ui.widgets.settings.panel import SettingsPanel


@pytest.fixture
def world(qapp, monkeypatch, tmp_path):
    state = SimpleNamespace(fingerprint=None, backend=None, vad=True)
    monkeypatch.setattr(model_catalog, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(wakeword_page, "load_fingerprint", lambda: state.fingerprint)
    monkeypatch.setattr(wakeword_page, "unavailable_reason", lambda _: state.backend)
    monkeypatch.setattr(wakeword_page, "is_vad_model_downloaded", lambda _: state.vad)
    runner = ModelDownloads(qapp)
    monkeypatch.setattr(qapp, "_roomkit_model_downloads", runner, raising=False)
    state.runner = runner
    state.widgets = []

    def open_widget(widget_type, *args):
        widget = widget_type(*args)
        state.widgets.append(widget)
        return widget

    state.open = open_widget
    yield state
    for widget in state.widgets:
        if shiboken6.isValid(widget):
            shiboken6.delete(widget)
    shiboken6.delete(runner)


def _encoder_exists():
    path = model_catalog.wakeword_encoder_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"test-encoder")


def _fingerprint():
    return SimpleNamespace(
        usable=True, label="Bonjour <RoomKit>", prototypes=[1, 2, 3], decoys=[1]
    )


async def _until(condition):
    for _ in range(500):
        if condition():
            return
        await asyncio.sleep(0.01)
    assert condition(), "Background work did not reach the expected state"


def test_dictation_preserves_a_missing_model_and_does_not_replace_it_on_refresh(
    world, monkeypatch
):
    available = {"parakeet-offline"}
    monkeypatch.setattr(model_manager, "is_model_downloaded", lambda key: key in available)
    page = world.open(_DictationPage, {"stt_provider": "local", "stt_model": "whisper-small"})
    assert page.selected_model_id() == "whisper-small"
    assert "not downloaded" in page._model_combo.currentText()
    assert not page._no_models_hint.isHidden()
    available.add("whisper-small")
    page.refresh_model_combo()
    assert page.selected_model_id() == "whisper-small"
    assert "not downloaded" not in page._model_combo.currentText()
    assert page._no_models_hint.isHidden()
    page._model_combo.setCurrentIndex(page._model_combo.findData("parakeet-offline"))
    available.clear()
    page.refresh_model_combo()
    assert page.get_settings()["stt_model"] == "parakeet-offline"


def test_disabling_or_switching_dictation_keeps_its_choices(world, monkeypatch):
    monkeypatch.setattr(model_manager, "is_model_downloaded", lambda key: key == "whisper-small")
    settings = {
        "stt_enabled": True,
        "stt_provider": "local",
        "stt_model": "whisper-small",
        "stt_translate": True,
        "stt_hotkey": "<ctrl>+<shift>+d",
        "dictation_language": "de",
    }
    page = world.open(_DictationPage, settings)
    for index in (0, 1, 2):
        page.stt_provider.setCurrentIndex(index)
        assert page.translate.isChecked()
        assert page._translation_row.isHidden() == (index != 2)
    page.enabled.setChecked(False)
    assert not page.hotkey.isEnabled()
    assert page.get_settings() == {**settings, "stt_enabled": False}


@pytest.mark.parametrize("blocked", ["backend", "vad", "encoder", "phrase"])
def test_wakeword_refresh_preserves_intent_when_a_prerequisite_is_missing(world, blocked):
    world.fingerprint = _fingerprint()
    if blocked != "encoder":
        _encoder_exists()
    if blocked == "backend":
        world.backend = "Install the wakeword component"
    elif blocked == "vad":
        world.vad = False
    elif blocked == "phrase":
        world.fingerprint = None
    settings = {
        "wakeword_enabled": True,
        "wakeword_sensitivity": "responsive",
        "idle_hangup_enabled": False,
        "idle_hangup_seconds": 35,
    }
    page = world.open(wakeword_page._WakeWordPage, settings)
    page.refresh()
    assert page.get_settings() == settings
    assert page._enabled.isEnabled()  # A blocked feature can still be switched off.
    page._enabled.setChecked(False)
    assert not page._enabled.isEnabled()
    assert page.get_settings()["wakeword_enabled"] is False
    assert not page._hangup_seconds.isEnabled()
    page._hangup_enabled.setChecked(True)
    assert page._hangup_seconds.isEnabled()
    assert page._hangup_seconds.value() == 35


def test_forgetting_a_phrase_is_immediate_and_explicit(world, monkeypatch):
    _encoder_exists()
    world.fingerprint = _fingerprint()
    monkeypatch.setattr(
        wakeword_page, "clear_fingerprint", lambda: setattr(world, "fingerprint", None)
    )
    page = world.open(wakeword_page._WakeWordPage, {"wakeword_enabled": True})
    assert "Bonjour <RoomKit>" in page._status.text()
    page._forget_button.click()
    assert world.fingerprint is None
    assert not page._enabled.isChecked()
    assert not page._forget_button.isEnabled()
    assert model_catalog.is_wakeword_encoder_downloaded()


async def test_wakeword_and_library_share_download_progress_across_closure(
    world, monkeypatch, qapp
):
    gate = asyncio.Event()
    calls = []

    async def download(progress):
        calls.append(True)
        progress(42, 100)
        await gate.wait()
        _encoder_exists()

    monkeypatch.setattr(encoder_download, "download_encoder", download)
    page = world.open(wakeword_page._WakeWordPage, {})
    page._encoder_row.action_btn.click()
    await _until(lambda: page._encoder_row.phase == "downloading")
    shiboken6.delete(page)
    library = world.open(_ModelsPage, {})
    row = library.rows[model_catalog.WAKEWORD_ENCODER_ID]
    assert row.progress_bar.value() == 42
    world.runner.start(row.model)
    reopened = world.open(wakeword_page._WakeWordPage, {})
    assert reopened._encoder_row.progress_bar.value() == 42
    for theme in ("light", "dark"):
        apply_theme(theme)
        qapp.processEvents()
        assert reopened._encoder_row.progress_bar.value() == 42
    gate.set()
    await _until(lambda: not world.runner._tasks)
    assert len(calls) == 1
    assert row.phase == reopened._encoder_row.phase == "downloaded"
    assert reopened._setup_button.isEnabled()
    assert not reopened._enabled.isEnabled()  # A phrase still needs to be recorded.


async def test_download_failure_survives_reopening_and_can_be_retried(world, monkeypatch):
    attempts = []

    async def download(progress):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("Checksum mismatch")
        _encoder_exists()

    monkeypatch.setattr(encoder_download, "download_encoder", download)
    page = world.open(wakeword_page._WakeWordPage, {})
    page._encoder_row.action_btn.click()
    await _until(lambda: not world.runner._tasks)
    shiboken6.delete(page)
    reopened = world.open(wakeword_page._WakeWordPage, {})
    assert "Checksum mismatch" in reopened._status.text()
    assert reopened._encoder_row.action_btn.text() == "Retry download"
    reopened._encoder_row.action_btn.click()
    await _until(lambda: not world.runner._tasks)
    assert len(attempts) == 2
    assert reopened._setup_button.isEnabled()
    assert "Checksum mismatch" not in reopened._status.text()


def test_encoder_deletion_only_removes_its_model_file(world):
    _encoder_exists()
    fingerprint = model_catalog.wakeword_encoder_path().with_name("fingerprint.json")
    fingerprint.write_text("saved phrase")
    wakeword_encoder_model().delete()
    assert not model_catalog.is_wakeword_encoder_downloaded()
    assert fingerprint.read_text() == "saved phrase"


@pytest.mark.parametrize(
    ("query", "page_key", "field"),
    [
        ("Dictation shortcut", "dictation", "enabled"),
        ("Dictation local model", "dictation", "stt_provider"),
        ("Translate dictation to English", "dictation", "stt_provider"),
        ("Record a wake phrase", "wakeword", "requirements.button"),
        ("Quiet period", "wakeword", "_hangup_enabled"),
    ],
)
def test_search_explains_prerequisites_without_enabling_them(world, qapp, query, page_key, field):
    save_settings({"stt_enabled": False, "stt_provider": "openai", "idle_hangup_enabled": False})
    panel = world.open(SettingsPanel)
    before = {**panel.page("dictation").get_settings(), **panel.page("wakeword").get_settings()}
    panel.show()
    panel.activateWindow()
    panel._search.setText(query)
    panel._search_results.activate_current()
    qapp.processEvents()
    page = panel.page(page_key)
    assert panel._resolve(page, field).hasFocus()
    assert {
        **panel.page("dictation").get_settings(),
        **panel.page("wakeword").get_settings(),
    } == before
    assert not panel._search_notice.text().startswith("Found:")


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("page_key", ["dictation", "wakeword"])
def test_voice_pages_fit_at_minimum_width_and_keep_edits_through_theme_changes(
    world, qapp, theme, page_key
):
    save_settings({"stt_provider": "local", "stt_model": "whisper-small"})
    panel = world.open(SettingsPanel)
    panel.show()
    panel.resize(panel.minimumSize())
    panel._sidebar.select_page(page_key)
    page = panel.page(page_key)
    before = page.get_settings()
    apply_theme(theme)
    qapp.processEvents()
    panel.grab()
    assert panel._scrolls[page_key].horizontalScrollBar().maximum() == 0
    assert page.get_settings() == before
    for field in page.findChildren(QComboBox):
        if field.isVisible():
            assert field.height() >= field.minimumSizeHint().height()
    panel.reject()
    saved = load_settings()
    for key, value in before.items():
        assert saved[key] == value


def test_wakeword_wizard_uses_pending_audio_settings(world, monkeypatch):
    from roomkit_ui.widgets import wakeword_wizard

    opened = {}

    class Wizard:
        def __init__(self, *_args, **kwargs):
            opened.update(kwargs)

        def exec(self):
            return 0

    monkeypatch.setattr(wakeword_wizard, "WakeWordWizard", Wizard)
    save_settings({"input_device": None, "provider": "openai", "conversation_mode": "realtime"})
    panel = world.open(SettingsPanel)
    panel.page("audio").processing.input_combo.addItem("Pending microphone", 42)
    panel.page("audio").processing.input_combo.setCurrentIndex(
        panel.page("audio").processing.input_combo.count() - 1
    )
    panel._sidebar.select_page("wakeword")
    panel.page("wakeword")._open_wizard()
    assert opened["input_device"] == 42
    assert opened["capture_rate"] == 24000
    assert load_settings()["input_device"] is None
