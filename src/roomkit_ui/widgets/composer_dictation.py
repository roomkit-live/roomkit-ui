"""Route the shared dictation engine to an editable conversation draft."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Slot

from roomkit_ui.engine_state import EngineState
from roomkit_ui.settings import load_settings
from roomkit_ui.stt_engine import DictationState
from roomkit_ui.stt_sessions import dictation_unavailable
from roomkit_ui.text_chat import text_chat_unavailable

if TYPE_CHECKING:
    from roomkit_ui.widgets.main_window import MainWindow


class ComposerDictation(QObject):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.engine = window._stt
        self.composer = window._controls
        self._settings_open = False
        self.composer.dictation_requested.connect(self.toggle)
        self.composer.dictation_cancelled.connect(self.cancel)
        self.composer.draft_cleared.connect(self.cancel)
        self.engine.state_changed.connect(self._state_changed)
        self.engine.draft_ready.connect(self._text_ready)
        self.engine.error_occurred.connect(self._error)
        window._engine.state_changed.connect(self.refresh)
        window.settings_opened.connect(self._open_settings)
        window.settings_saved.connect(self._settings_saved)
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        self.composer.set_dictation_availability(dictation_unavailable(load_settings()))
        blocked = (
            self._settings_open
            or self.window._closed
            or self.window._start_pending
            or self.window._engine.state
            not in (EngineState.IDLE, EngineState.ERROR, EngineState.READY)
        )
        self.engine.set_start_blocked(
            "Finish the current activity before starting dictation." if blocked else ""
        )

    @Slot()
    def toggle(self) -> None:
        if self.engine.busy:
            if self.engine.to_input:
                self.engine.toggle_recording()
            return
        self.refresh()
        settings = load_settings()
        if reason := text_chat_unavailable(settings) or dictation_unavailable(settings):
            self.composer.show_dictation_error(reason)
            return
        self.engine.start_input()

    @Slot()
    def cancel(self) -> None:
        if self.engine.to_input:
            self.engine.cancel()

    @Slot(object)
    def _state_changed(self, state: DictationState) -> None:
        self.composer.set_dictation_state(state, external=not self.engine.to_input)
        self.window._history.drawer.set_busy(self.window._history.busy)
        if state is DictationState.IDLE and self.engine.to_input and not self.window._closed:
            self.composer.focus_input()

    @Slot(str)
    def _text_ready(self, text: str) -> None:
        if not self.window._closed:
            self.composer.insert_dictation(text)

    @Slot(str)
    def _error(self, message: str) -> None:
        if self.engine.to_input and not self.window._closed:
            self.composer.show_dictation_error(message)

    @Slot()
    def _open_settings(self) -> None:
        self._settings_open = True
        self.refresh()

    @Slot()
    def _settings_saved(self) -> None:
        self._settings_open = False
        self.refresh()
