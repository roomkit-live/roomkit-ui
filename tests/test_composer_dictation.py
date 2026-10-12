"""Dictation edits a draft without sending, pasting, or leaking into another thread."""

from __future__ import annotations

import asyncio

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from roomkit.voice.capture.mock import MockCaptureSource
from roomkit.voice.stt.mock import MockSTTProvider

from roomkit_ui import stt_engine, stt_sessions
from roomkit_ui.engine_audio import local_audio_backend
from roomkit_ui.engine_state import EngineState
from roomkit_ui.stt_engine import DictationState, STTEngine
from roomkit_ui.theme_live import apply_theme
from roomkit_ui.widgets.main_window import MainWindow


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


@pytest.fixture
def settings(monkeypatch):
    values = {
        "vc_llm_provider": "anthropic",
        "anthropic_api_key": "test-only",
        "stt_provider": "deepgram",
        "deepgram_api_key": "test-only",
        "stt_enabled": False,
    }
    for module in ("stt_engine", "widgets.main_window", "widgets.composer_dictation"):
        monkeypatch.setattr(f"roomkit_ui.{module}.load_settings", lambda: dict(values))
    monkeypatch.setattr("roomkit_ui.text_chat.is_available", lambda _: True)
    monkeypatch.setattr(stt_sessions, "unavailable_reason", lambda _: None)
    monkeypatch.delenv("STT_FAKE", raising=False)
    return values


@pytest.fixture
def window(qtbot, settings, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    def forbidden(*_args):
        pytest.fail("Draft dictation must not inspect focus, paste, or start a conversation")

    monkeypatch.setattr(stt_engine, "_get_frontmost_bundle", forbidden)
    monkeypatch.setattr(stt_engine, "_activate_bundle", forbidden)
    monkeypatch.setattr(window._engine, "start", forbidden)
    window._stt.text_ready.connect(forbidden)
    return window


class Capture:
    def __init__(self, engine, monkeypatch):
        self.engine = engine
        self.ready, self.finish, self.closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.ready.set()
        self.finish.set()
        self.closed.set()
        self.text = "la suite"
        self.opens = 0
        self.closes = 0
        self.collecting = False
        self.closing = False
        monkeypatch.setattr(engine, "_open_session", self.open)
        monkeypatch.setattr(engine, "_collect_final_text", self.collect)

    async def open(self):
        self.opens += 1
        self.engine._kit = self
        await self.ready.wait()
        return True

    async def collect(self, _objects):
        self.collecting = True
        await self.finish.wait()
        self.engine._accumulated_text.append(self.text)

    async def close(self):
        self.closing = True
        await self.closed.wait()
        self.closes += 1


async def test_finish_inserts_at_the_cursor_keeps_images_and_never_sends(window, monkeypatch):
    capture = Capture(window._stt, monkeypatch)
    composer = window._controls
    editor = composer._input
    editor.setPlainText("Voici: !")
    cursor = editor.textCursor()
    cursor.setPosition(7)
    editor.setTextCursor(cursor)
    image = QImage(30, 20, QImage.Format_RGB32)
    image.fill(QColor("#7360cc"))
    composer._attachments.add_image(image)
    images = composer.images
    QApplication.clipboard().setText("untouched clipboard")
    composer._dictation_button.setFocus(Qt.TabFocusReason)
    QTest.keyClick(composer._dictation_button, Qt.Key_Space)
    assert window._stt.busy  # Claimed before the asynchronous start.
    assert not composer._live_button.isEnabled()
    assert editor.isReadOnly()
    await until(lambda: window._stt.state is DictationState.RECORDING)
    for theme in ("light", "dark"):
        apply_theme(theme)
        assert composer._dictation_label.text() == "Listening…"
        assert composer._dictation_button.accessibleName() == "Finish dictation"
    composer._dictation_button.click()
    await until(lambda: not window._stt.busy)
    assert editor.toPlainText() == "Voici: la suite!"
    assert composer.images == images
    assert composer._dictation_feedback.isHidden()
    assert not editor.isReadOnly()
    assert QApplication.clipboard().text() == "untouched clipboard"
    assert window._chat.snapshot() == [] and window._history.current is None
    assert capture.opens == capture.closes == 1
    editor.undo()
    assert editor.toPlainText() == "Voici: !"


@pytest.mark.parametrize("phase", ["starting", "recording", "transcribing"])
async def test_cancel_preserves_draft_and_drops_late_results(window, monkeypatch, phase):
    capture = Capture(window._stt, monkeypatch)
    composer = window._controls
    composer._input.setPlainText("Keep this")
    if phase == "starting":
        capture.ready.clear()
    if phase == "transcribing":
        capture.finish.clear()
    composer._dictation_button.click()
    await until(lambda: capture.opens)
    if phase != "starting":
        await until(lambda: window._stt.state is DictationState.RECORDING)
    if phase == "transcribing":
        composer._dictation_button.click()
        await until(lambda: capture.collecting)
        assert composer._dictation_label.text() == "Transcribing…"
    composer._cancel_dictation.click()
    await until(lambda: not window._stt.busy)
    capture.ready.set()
    capture.finish.set()
    assert composer._input.toPlainText() == "Keep this"
    assert capture.closes == 1
    assert not window._stt._cleanup_tasks


async def test_capture_blocks_navigation_send_live_and_reentry_until_cleanup(window, monkeypatch):
    capture = Capture(window._stt, monkeypatch)
    capture.closed.clear()
    composer = window._controls
    composer._input.setPlainText("Draft")
    composer._dictation_button.click()
    window._history.new()
    window._on_start()
    window._on_send("Cannot send yet")
    assert composer._input.toPlainText() == "Draft"
    assert not window._stt.start_input()
    await until(lambda: window._stt.state is DictationState.RECORDING)
    window._stt.toggle_recording()  # A global hotkey finishes the same input capture.
    await until(lambda: capture.closing)
    assert window._stt.busy and window._history.busy
    assert not composer._dictation_button.isEnabled()
    window._stt.toggle_recording()  # Cannot queue a system-wide paste from this draft.
    composer._cancel_dictation.click()  # Cancellation must still await teardown.
    await asyncio.sleep(0)
    assert window._stt.busy
    capture.closed.set()
    await until(lambda: not window._stt.busy)
    assert capture.opens == capture.closes == 1
    assert composer._input.toPlainText() == "Draft"
    assert not window._history.busy
    window._history.new()
    assert composer._input.toPlainText() == ""


async def test_closing_during_start_releases_capture_without_changing_the_draft(
    window, monkeypatch
):
    capture = Capture(window._stt, monkeypatch)
    capture.ready.clear()
    window._controls._dictation_button.click()
    await until(lambda: capture.opens)
    window.close()
    await window._stt.shutdown()
    assert capture.closes == 1 and not window._stt.busy
    assert window._controls._input.toPlainText() == ""


@pytest.mark.parametrize("failure", ["empty", "start", "finish"])
async def test_failed_dictation_leaves_an_editable_draft_and_recoverable_feedback(
    window, monkeypatch, failure
):
    capture = Capture(window._stt, monkeypatch)
    capture.text = ""

    async def fail(*_args):
        raise RuntimeError("Microphone unavailable")

    if failure != "empty":
        monkeypatch.setattr(
            window._stt, "_open_session" if failure == "start" else "_collect_final_text", fail
        )
    composer = window._controls
    composer._input.setPlainText("Keep this")
    composer._dictation_button.click()
    if failure != "start":
        await until(lambda: window._stt.state is DictationState.RECORDING)
        composer._dictation_button.click()
    await until(lambda: not window._stt.busy)
    assert composer._input.toPlainText() == "Keep this"
    assert not composer._input.isReadOnly()
    assert not composer._dictation_feedback.isHidden()
    assert composer._dictation_button.isEnabled()
    composer._cancel_dictation.click()
    assert composer._dictation_feedback.isHidden()


def test_settings_refresh_gates_mic_but_keeps_typing_available(window, settings):
    composer = window._controls
    assert composer._dictation_button.isEnabled()  # Global hotkey activation is independent.
    settings["deepgram_api_key"] = ""
    window.settings_saved.emit()
    assert not composer._dictation_button.isEnabled()
    assert "Deepgram" in composer._dictation_button.toolTip()
    assert composer._input.isEnabled()
    settings["deepgram_api_key"] = "test-only"
    window.settings_saved.emit()
    assert composer._dictation_button.isEnabled()
    settings["anthropic_api_key"] = ""
    window.settings_saved.emit()
    assert not composer._dictation_button.isEnabled()


@pytest.mark.parametrize(
    "state", [EngineState.CONNECTING, EngineState.ACTIVE, EngineState.STOPPING]
)
def test_live_and_text_replies_prevent_dictation(window, state):
    for text_mode in (False, True):
        window._engine._state = state
        window._engine._text_request = "test" if text_mode else None
        window._on_state_changed(state)
        window._dictation.refresh()
        assert not window._stt.start_input()
        assert not window._controls._dictation_button.isEnabled()
    window._engine._state = EngineState.IDLE
    window._engine._text_request = None
    window._on_state_changed(EngineState.IDLE)


@pytest.mark.parametrize("streaming", [False, True])
async def test_real_roomkit_capture_flushes_all_audio_on_finish(qapp, monkeypatch, streaming):
    source = MockCaptureSource()
    provider = MockSTTProvider(["les derniers mots"], streaming=streaming)
    backend = local_audio_backend(input_sample_rate=16000, source=source)
    monkeypatch.setattr(stt_sessions, "local_audio_backend", lambda **_: backend)
    engine = STTEngine()
    result = []
    engine.draft_ready.connect(result.append)

    async def open_session():
        return await engine._start_vc_dictation(
            stt=provider,
            batch_mode=not streaming,
            log_extra={},
            settings={},
            log_partials=False,
            error_context="test",
        )

    monkeypatch.setattr(engine, "_open_session", open_session)
    engine.start_input()
    await until(lambda: engine.state is DictationState.RECORDING)
    chunks = source.feed_blocks(4)
    await until(lambda: engine._channel.stt_buffer_size(engine._local_session) > 0)
    assert len(backend.list_sessions("stt-room")) == 1
    engine.toggle_recording()
    await until(lambda: not engine.busy)
    assert result == ["les derniers mots"]
    assert provider.calls[0].data == b"".join(chunks)
    assert backend.list_sessions("stt-room") == []


def test_insertion_uses_unicode_cursor_positions_and_replaces_selection(window):
    composer = window._controls
    composer._input.setPlainText("😀 ancien!")
    cursor = composer._input.textCursor()
    cursor.setPosition(3)
    cursor.setPosition(9, QTextCursor.KeepAnchor)
    composer._input.setTextCursor(cursor)
    composer.set_dictation_state(DictationState.STARTING)
    composer.insert_dictation("nouveau")
    composer.set_dictation_state(DictationState.IDLE)
    assert composer._input.toPlainText() == "😀 nouveau!"


@pytest.mark.parametrize(
    "settings, reason",
    [
        ({"stt_provider": "unknown"}, "Dictation"),
        ({"stt_provider": "local", "stt_model": "absent"}, "Download"),
        ({"stt_provider": "openai", "openai_api_key": " "}, "OpenAI"),
    ],
)
def test_missing_dictation_configuration(settings, reason, monkeypatch):
    monkeypatch.setattr(stt_sessions, "unavailable_reason", lambda _: None)
    monkeypatch.setattr(stt_sessions, "is_model_downloaded", lambda _: False)
    assert reason in stt_sessions.dictation_unavailable(settings)


async def test_cancel_in_the_same_tick_never_opens_a_microphone(window, monkeypatch):
    capture = Capture(window._stt, monkeypatch)
    window._controls._dictation_button.click()
    window._controls._cancel_dictation.click()
    await until(lambda: not window._stt.busy)
    assert capture.opens == capture.closes == 0


async def test_a_global_dictation_cannot_be_redirected_into_the_composer(window, monkeypatch):
    capture = Capture(window._stt, monkeypatch)
    monkeypatch.setattr(stt_engine, "_get_frontmost_bundle", lambda: None)
    window._stt.toggle_recording()
    assert not window._controls._dictation_button.isEnabled()
    assert not window._controls._live_button.isEnabled()
    window._dictation.toggle()
    await until(lambda: window._stt.state is DictationState.RECORDING)
    assert capture.opens == 1 and not window._stt.to_input
    await window._stt.shutdown()
    assert window._controls._dictation_button.isEnabled()
    assert window._controls._input.toPlainText() == ""


async def test_cancel_while_startup_cleans_up_still_waits_for_the_microphone(window, monkeypatch):
    capture = Capture(window._stt, monkeypatch)
    capture.closed.clear()

    async def failed_start():
        window._stt._kit = capture
        return False

    monkeypatch.setattr(window._stt, "_open_session", failed_start)
    window._controls._dictation_button.click()
    await until(lambda: capture.closing)
    window._controls._cancel_dictation.click()
    await asyncio.sleep(0)
    assert window._stt.busy
    capture.closed.set()
    await until(lambda: not window._stt.busy)
    assert capture.closes == 1
