"""System tray icon for the STT dictation service."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from room_ui.icons import svg_icon

logger = logging.getLogger(__name__)

# Tray icon colours
_COLOR_IDLE = "#AAAAAA"
_COLOR_RECORDING = "#FF4444"

# RoomKit logo for the tray (falls back to microphone SVG if missing)
_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "icon.png"


class TrayService(QObject):
    """Manages a ``QSystemTrayIcon`` showing dictation status."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self._recording = False

        # --- Icon ---
        if _LOGO_PATH.exists():
            self._icon_idle = QIcon(str(_LOGO_PATH))
        else:
            self._icon_idle = svg_icon("microphone", color=_COLOR_IDLE, size=64)
        self._icon_recording = svg_icon("microphone", color=_COLOR_RECORDING, size=64)

        self._tray = QSystemTrayIcon(self._icon_idle, self)

        # --- Context menu ---
        menu = QMenu()
        self._show_action = QAction("Show Window", menu)
        menu.addAction(self._show_action)
        menu.addSeparator()
        self._dictate_action = QAction("Start Dictation", menu)
        menu.addAction(self._dictate_action)
        self._log_action = QAction("Show Log", menu)
        menu.addAction(self._log_action)
        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.setToolTip("RoomKit Dictation — idle")
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    @property
    def show_action(self) -> QAction:
        """Expose the show-window action so ``app.py`` can connect it."""
        return self._show_action

    @property
    def dictate_action(self) -> QAction:
        """Expose the menu action so ``app.py`` can connect it."""
        return self._dictate_action

    @property
    def log_action(self) -> QAction:
        """Expose the log action so ``app.py`` can connect it."""
        return self._log_action

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Left-click the tray icon to show the main window."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_action.trigger()

    @Slot(bool)
    def on_recording_changed(self, recording: bool) -> None:
        self._recording = recording
        if recording:
            self._tray.setIcon(self._icon_recording)
            self._tray.setToolTip("RoomKit Dictation — recording...")
            self._dictate_action.setText("Stop Dictation")
        else:
            self._tray.setIcon(self._icon_idle)
            self._tray.setToolTip("RoomKit Dictation — idle")
            self._dictate_action.setText("Start Dictation")

    @Slot(str)
    def on_text_ready(self, text: str) -> None:
        preview = text[:80] + ("…" if len(text) > 80 else "")
        self._tray.showMessage(
            "Dictation — copied to clipboard",
            preview,
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    @Slot(str)
    def on_error(self, message: str) -> None:
        self._tray.showMessage(
            "Dictation Error",
            message,
            QSystemTrayIcon.MessageIcon.Critical,
            4000,
        )
