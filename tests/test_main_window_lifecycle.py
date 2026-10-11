"""MainWindow lifecycles: what must survive a teardown, and what must go."""

from __future__ import annotations

import asyncio

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


# -- start while the engine is busy ---------------------------------------------


def test_a_toggle_while_stopping_keeps_the_chat(window, monkeypatch):
    # The engine refuses a start until it is IDLE or ERROR; the chat must not
    # be wiped for a start that never happens.
    window._chat.add_info("Last answer before the stop")
    monkeypatch.setattr(type(window._engine), "state", property(lambda _e: EngineState.STOPPING))

    window.toggle_session()

    assert "Last answer before the stop" in _chat_texts(window)


# -- MCP Apps ------------------------------------------------------------------


class _FakeAppWidget:
    """Stands in for MCPAppWidget (a QWebEngineView) and records what it gets."""

    def __init__(self) -> None:
        self.tool_call_requested = _FakeSignal()
        self.results: list[str] = []

    def send_tool_input(self, _arguments) -> None:
        pass

    def send_tool_result(self, result: str) -> None:
        self.results.append(result)


class _FakeSignal:
    def connect(self, _slot) -> None:
        pass


class _SlowMCP:
    """read_resource() lets *during_load* run while the HTML is "loading"."""

    def __init__(self, during_load) -> None:
        self._during_load = during_load

    async def read_resource(self, _name, _uri) -> str:
        self._during_load()
        return "<html></html>"


@pytest.fixture
def inserted_apps(window, monkeypatch) -> list[_FakeAppWidget]:
    """The MCP App widgets the chat is asked to show, in an active session."""
    inserted: list[_FakeAppWidget] = []

    def add_app_tool_call(*_args):
        inserted.append(_FakeAppWidget())
        return inserted[-1]

    monkeypatch.setattr(window._chat, "add_app_tool_call", add_app_tool_call)
    window._engine._state = EngineState.ACTIVE
    return inserted


def _end_session(window: MainWindow) -> None:
    window._engine._state = EngineState.IDLE
    window._on_state_changed(EngineState.IDLE)


async def test_an_app_loaded_after_the_session_ended_is_not_shown(window, inserted_apps):
    window._engine._mcp = _SlowMCP(lambda: _end_session(window))

    await window._fetch_and_show_app("chart", "{}", "ui://chart", "viz")

    assert inserted_apps == []
    assert window._active_app_widgets == {}


async def test_an_app_loaded_while_the_session_runs_is_shown(window, inserted_apps):
    window._engine._mcp = _SlowMCP(lambda: None)

    await window._fetch_and_show_app("chart", "{}", "ui://chart", "viz")

    assert len(inserted_apps) == 1
    assert window._active_app_widgets["chart"] is inserted_apps[0]


async def test_a_new_session_forgets_the_previous_app_widgets(window, monkeypatch):
    stale = _FakeAppWidget()
    window._active_app_widgets["chart"] = stale

    async def start(*_args):
        pass

    monkeypatch.setattr(window._engine, "start", start)
    window._on_start()  # clears the chat, stale widget included
    await asyncio.sleep(0)  # let the (fake) engine start run
    window._on_tool_result_app("chart", "{}")

    assert stale.results == []
