"""Main window assembling all panels and wiring signals."""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from room_ui.engine import Engine
from room_ui.settings import load_settings
from room_ui.theme import colors
from room_ui.widgets.chat_view import ChatView
from room_ui.widgets.control_bar import ControlBar
from room_ui.widgets.settings_panel import SettingsPanel
from room_ui.widgets.vu_meter import VUMeter

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RoomKit UI")
        self.setFixedWidth(420)
        self.setMinimumHeight(600)
        self.resize(420, 700)

        self._engine = Engine(self)
        c = colors()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Chat ──
        self._chat = ChatView()
        root.addWidget(self._chat, 1)

        # ── VU Meter ──
        self._vu = VUMeter()
        root.addWidget(self._vu)

        # ── Separator ──
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {c['SEPARATOR']};")
        root.addWidget(sep)

        # ── Control bar ──
        self._controls = ControlBar()
        self._controls.setStyleSheet(
            f"ControlBar {{ background-color: {c['BG_SECONDARY']}; }}"
        )
        root.addWidget(self._controls)

        # ── Signals ──
        self._controls.start_requested.connect(self._on_start)
        self._controls.stop_requested.connect(self._on_stop)
        self._controls.mute_toggled.connect(self._engine.set_mic_muted)
        self._controls.settings_requested.connect(self._open_settings)
        self._controls.reset_requested.connect(self._on_reset)

        self._engine.state_changed.connect(self._on_state_changed)
        self._engine.transcription.connect(self._on_transcription)
        self._engine.mic_audio_level.connect(self._vu.set_mic_level)
        self._engine.speaker_audio_level.connect(self._vu.set_speaker_level)
        self._engine.user_speaking.connect(self._on_user_speaking)
        self._engine.ai_speaking.connect(self._on_ai_speaking)
        self._engine.error_occurred.connect(self._on_error)
        self._engine.tool_use.connect(self._on_tool_use)
        self._engine.mcp_status.connect(self._on_mcp_status)

    def _open_settings(self) -> None:
        SettingsPanel(self).exec()

    def _on_reset(self) -> None:
        if self._engine.state != "idle":
            asyncio.ensure_future(self._engine.stop())
        self._chat.reset()

    def _on_start(self) -> None:
        self._chat.clear()
        try:
            asyncio.ensure_future(self._engine.start(load_settings()))
        except Exception as e:
            logger.exception("Failed to schedule engine start")
            self._chat.add_error(str(e))

    def _on_stop(self) -> None:
        try:
            asyncio.ensure_future(self._engine.stop())
        except Exception as e:
            logger.exception("Failed to schedule engine stop")
            self._chat.add_error(str(e))

    def _on_state_changed(self, state: str) -> None:
        self._controls.set_state(state)
        if state == "active":
            self._vu.start()
        elif state in ("idle", "error"):
            self._vu.stop()

    def _on_transcription(self, text: str, role: str, is_final: bool) -> None:
        self._chat.add_transcription(text, role, is_final)

    def _on_user_speaking(self, speaking: bool) -> None:
        if speaking:
            self._chat.show_listening()
        else:
            self._chat.hide_status()

    def _on_ai_speaking(self, speaking: bool) -> None:
        if speaking:
            self._chat.show_thinking()
        else:
            self._chat.hide_status()

    def _on_mcp_status(self, message: str) -> None:
        self._chat.add_info(message)

    def _on_tool_use(self, name: str, arguments: str) -> None:
        logger.info("Tool call: %s(%s)", name, arguments)
        self._chat.add_tool_call(name, arguments)

    def _on_error(self, msg: str) -> None:
        logger.error("Engine error: %s", msg)
        self._chat.add_error(msg)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._engine.state != "idle":
            asyncio.ensure_future(self._engine.stop())
        super().closeEvent(event)
