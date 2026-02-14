"""System tray icon for the STT dictation service."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from roomkit_ui.icons import svg_icon

logger = logging.getLogger(__name__)

# Tray icon colours
_COLOR_IDLE = "#AAAAAA"
_COLOR_RECORDING = "#FF4444"

# RoomKit logo for the tray (falls back to microphone SVG if missing)
_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "icon.png"


def _icon_with_dot(base_icon: QIcon, color: str, size: int = 64) -> QIcon:
    """Return *base_icon* with a small coloured dot in the bottom-right corner."""
    pixmap = base_icon.pixmap(size, size)
    if pixmap.isNull():
        return base_icon

    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)

    dot_d = max(int(size * 0.30), 8)  # dot diameter ~30% of icon
    margin = max(int(size * 0.02), 1)
    x = size - dot_d - margin
    y = size - dot_d - margin

    # White border ring
    p.setPen(QPen(QColor("#FFFFFF"), max(int(dot_d * 0.18), 2)))
    p.setBrush(QColor(color))
    p.drawEllipse(x, y, dot_d, dot_d)
    p.end()

    return QIcon(pixmap)


class TrayService(QObject):
    """Manages a ``QSystemTrayIcon`` showing dictation and session status."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self._recording = False
        self._session_active = False

        # --- Icon ---
        if _LOGO_PATH.exists():
            self._icon_idle = QIcon(str(_LOGO_PATH))
        else:
            self._icon_idle = svg_icon("microphone", color=_COLOR_IDLE, size=64)
        self._icon_recording = svg_icon("microphone", color=_COLOR_RECORDING, size=64)
        self._icon_session = _icon_with_dot(self._icon_idle, "#30D158")

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
    def on_session_changed(self, active: bool) -> None:
        """Update the tray icon to reflect voice-assistant session state."""
        self._session_active = active
        self._refresh_icon()

    @Slot(bool)
    def on_recording_changed(self, recording: bool) -> None:
        self._recording = recording
        self._dictate_action.setText("Stop Dictation" if recording else "Start Dictation")
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        """Pick the right icon based on recording and session state."""
        if self._recording:
            self._tray.setIcon(self._icon_recording)
            self._tray.setToolTip("RoomKit — dictation recording...")
        elif self._session_active:
            self._tray.setIcon(self._icon_session)
            self._tray.setToolTip("RoomKit — session active")
        else:
            self._tray.setIcon(self._icon_idle)
            self._tray.setToolTip("RoomKit — idle")

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

    @Slot()
    def on_permission_required(self) -> None:
        self._tray.showMessage(
            "Accessibility Permission Required",
            "Global hotkeys need Accessibility access.\n"
            "Go to System Settings → Privacy & Security → Accessibility "
            "and add this app.",
            QSystemTrayIcon.MessageIcon.Warning,
            6000,
        )
