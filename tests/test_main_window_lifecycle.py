"""MainWindow lifecycles: what must survive a teardown, and what must go."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel
from shiboken6 import isValid

import roomkit_ui.widgets.main_window as main_window_mod
from roomkit_ui.engine_state import EngineState
from roomkit_ui.widgets.main_window import MainWindow
from roomkit_ui.widgets.settings import SettingsPanel


def _flush_deletes() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def window(qapp):
    w = MainWindow()
    yield w
    w.deleteLater()
    _flush_deletes()


# -- Settings dialog -----------------------------------------------------------


def test_a_closed_settings_dialog_is_destroyed(window, monkeypatch):
    opened: list[SettingsPanel] = []

    class _ClosesAtOnce(SettingsPanel):
        def exec(self) -> int:
            opened.append(self)
            self.reject()
            return 0

    monkeypatch.setattr(main_window_mod, "SettingsPanel", _ClosesAtOnce)

    window._open_settings()
    _flush_deletes()

    assert len(opened) == 1
    assert not isValid(opened[0])


# -- idle hang-up notice -------------------------------------------------------


def _chat_texts(window: MainWindow) -> list[str]:
    layout = window._chat._layout
    widgets = (layout.itemAt(i).widget() for i in range(layout.count()))
    return [w.text() for w in widgets if isinstance(w, QLabel) and w.isVisibleTo(window)]


def test_the_idle_hangup_reason_outlives_the_session_end(window, monkeypatch):
    monkeypatch.setattr(window, "_on_stop", lambda: None)  # the engine is not running
    reason = "Session closed after 15 s of silence."

    window._on_idle_hangup(reason)
    assert reason in _chat_texts(window)

    window._on_state_changed(EngineState.IDLE)  # the chat resets here
    _flush_deletes()

    assert reason in _chat_texts(window)


def test_an_ordinary_session_end_leaves_no_stale_notice(window, monkeypatch):
    monkeypatch.setattr(window, "_on_stop", lambda: None)
    window._on_idle_hangup("Session closed after 15 s of silence.")
    window._on_state_changed(EngineState.IDLE)

    window._on_state_changed(EngineState.IDLE)  # the next session ends normally

    assert "Session closed after 15 s of silence." not in _chat_texts(window)
