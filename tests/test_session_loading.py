"""Loading occupies the transcript slot and keeps cancellation reachable."""

import asyncio

from roomkit_ui.engine_state import EngineState
from roomkit_ui.widgets.main_window import MainWindow


async def test_model_loading_can_be_cancelled_without_covering_the_controls(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    stops = []

    async def stop():
        stops.append(True)

    monkeypatch.setattr(window._engine, "stop", stop)
    window._chat.clear()
    window._engine.state_changed.emit(EngineState.CONNECTING)
    window._engine.loading_status.emit("Starting llama.cpp — the first run downloads the model…")
    assert window._conversation_stack.currentWidget() is window._loading
    assert window._loading._status.text() == "Preparing your models…"
    assert window._controls._live_button.isVisibleTo(window)
    assert window._controls._mute_button.isHidden()
    assert window._header.isHidden()
    window._controls._live_button.click()
    await asyncio.sleep(0)
    assert stops == [True]

    window._engine.state_changed.emit(EngineState.STOPPING)
    window._engine.loading_status.emit("Loading TTS model…")  # a late worker callback
    assert window._loading._status.text() == "Closing the connection…"
    assert window._loading._progress.isHidden()
    assert not window._controls._live_button.isEnabled()
    window._engine.state_changed.emit(EngineState.IDLE)
    assert window._conversation_stack.currentWidget() is window._chat
    assert not window._header.isHidden()


def test_loading_failure_and_retry_do_not_leave_stale_content(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window._engine.state_changed.emit(EngineState.CONNECTING)
    window._engine.loading_status.emit("Loading STT model…")
    window._engine.state_changed.emit(EngineState.ERROR)
    assert window._conversation_stack.currentWidget() is window._chat
    window._engine.state_changed.emit(EngineState.CONNECTING)
    assert window._loading._status.text() == "Connecting your conversation…"
    assert not window._loading._progress.isHidden()
    window._engine.loading_status.emit("Loading skills…")
    assert window._loading._status.text() == "Connecting your conversation…"
    window._engine.state_changed.emit(EngineState.ACTIVE)
    assert window._conversation_stack.currentWidget() is window._chat
    assert window._loading.isHidden()
    assert not window._vu.isHidden()
