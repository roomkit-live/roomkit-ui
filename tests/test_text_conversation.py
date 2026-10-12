"""Typed turns keep the selected history, drafts and native UI coherent."""

import asyncio

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_engine_text import SETTINGS, TestProvider
from test_engine_text import setup_text as setup_text

from roomkit_ui.conversations import ConversationStore
from roomkit_ui.engine_state import EngineState
from roomkit_ui.widgets.main_window import MainWindow


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


def configure(monkeypatch, settings):
    monkeypatch.setattr("roomkit_ui.widgets.main_window.load_settings", lambda: dict(settings))


def test_settings_close_enables_or_disables_input_without_restart(qtbot, monkeypatch):
    monkeypatch.setattr("roomkit_ui.text_chat.is_available", lambda _: True)
    settings = {**SETTINGS, "anthropic_api_key": ""}
    configure(monkeypatch, settings)
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window._controls._input.isEnabled()
    settings["anthropic_api_key"] = "test-only"
    window.settings_saved.emit()
    assert window._controls._input.isEnabled()
    window._controls._input.setPlainText("Draft")
    settings["anthropic_api_key"] = ""
    window.settings_saved.emit()
    window._on_send("Draft")
    assert not window._controls._input.isEnabled()
    assert window._controls._input.toPlainText() == "Draft"
    assert window._history.current is None
    assert window._engine.state == EngineState.IDLE


@pytest.mark.parametrize("persistent", [True, False])
async def test_sending_streaming_and_followup_in_the_same_thread(
    qtbot,
    monkeypatch,
    setup_text,
    persistent,
):
    settings = {**SETTINGS, "conversation_memory": persistent}
    configure(monkeypatch, settings)
    window = MainWindow()
    qtbot.addWidget(window)
    # No external title request during this deterministic transport test.
    monkeypatch.setattr(window._history, "suggest_title", lambda **_: None)
    provider = TestProvider(pause=True)
    setup_text(provider, window._engine)
    audio_signals = []
    window.session_active_changed.connect(audio_signals.append)
    window.show()
    window._controls._input.setPlainText("Bonjour")
    QTest.keyClick(window._controls._input, Qt.Key_Return)
    window._on_send("Duplicate")  # same event-loop tick must not accept twice
    first_task = window._request_task
    assert window._chat.snapshot()[0]["text"] == "Bonjour"
    assert len(window._chat.snapshot()) == 1
    assert window._controls._input.toPlainText() == ""
    first_id = window._history.current.id
    window._history.new()  # connecting/pending generation cannot change its thread
    assert window._history.current.id == first_id
    await until(lambda: len(window._chat.snapshot()) == 2)
    assert not first_task.done()
    assert window._chat._bubbles()[-1]._label.text() == "Bonjour"
    assert not window._chat._bubbles()[-1]._stream_timer.isActive()
    assert window._conversation_stack.currentWidget() is window._chat
    assert window._vu.isHidden() and window._controls._mute_button.isHidden()
    assert not window._controls._input.isHidden()
    assert audio_signals == []
    window._controls._input.setPlainText("Et ensuite ?")
    provider.release.set()
    await asyncio.wait_for(first_task, 3)
    await until(lambda: not window._start_pending)
    assert window._controls._input.toPlainText() == "Et ensuite ?"
    assert window._chat.snapshot()[-1]["text"] == "Bonjour !"
    assert window._chat._text_pending is None
    assert window._history.current.title == "Bonjour"
    saved = ConversationStore().get(first_id)
    assert (saved is not None) == persistent
    if persistent:
        assert [entry["text"] for entry in saved.entries] == ["Bonjour", "Bonjour !"]
    else:
        assert not window._history.store.path.exists()
    kit = window._engine._kit
    window._controls._live_button.click()
    await asyncio.wait_for(window._request_task, 3)
    await until(lambda: not window._start_pending)
    assert window._history.current.id == first_id
    assert len(window._chat.snapshot()) == 4
    assert window._engine._kit is kit
    assert not provider.closed
    assert [m.content for m in provider.contexts[1].messages] == [
        "Bonjour",
        "Bonjour !",
        "Et ensuite ?",
    ]
    # New conversations do not inherit a draft meant for this one.
    window._controls._input.setPlainText("Old draft")
    window._history.new()
    await until(lambda: not window._start_pending)
    assert window._controls._input.toPlainText() == ""
    assert window._chat.snapshot() == []
    assert audio_signals == []


async def test_stopping_keeps_all_received_text_and_saves_interruption(
    qtbot, monkeypatch, setup_text
):
    configure(monkeypatch, SETTINGS)
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window._history, "suggest_title", lambda **_: None)
    provider = TestProvider(pause=True)
    setup_text(provider, window._engine)
    window._on_send("Salut")
    task = window._request_task
    await until(lambda: len(window._chat.snapshot()) == 2)
    window._controls._live_button.click()
    await until(lambda: window._engine.state == EngineState.READY)
    await asyncio.wait_for(task, 3)
    reply = window._chat.snapshot()[-1]
    assert reply["text"] == "Bonjour" and reply["interrupted"]
    assert window._history.current.entries[-1] == reply
    assert window._chat._text_pending is None
    assert window._controls._live_button.accessibleName() == "Start a live conversation"
    provider.release.set()
    window._history.new()
    await until(lambda: not window._start_pending)
    window._engine.transcription.emit("Too late", "assistant", True, "")
    assert window._chat.snapshot() == []


async def test_cancel_before_start_has_no_provider_call(qtbot, monkeypatch, setup_text):
    configure(monkeypatch, SETTINGS)
    window = MainWindow()
    qtbot.addWidget(window)
    provider = TestProvider()
    setup_text(provider, window._engine)
    window._on_send("Salut")
    window._on_stop()
    await until(lambda: not window._start_pending)
    assert provider.contexts == []
    assert window._engine.state == EngineState.IDLE
    assert window._chat._text_pending is None
    assert window._controls._live_button.accessibleName() == "Start a live conversation"
