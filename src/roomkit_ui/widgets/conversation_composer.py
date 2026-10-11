"""The first composer: reserved text input and working Live controls."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.engine_state import EngineState
from roomkit_ui.icons import svg_icon
from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.widgets.buttons import KeyboardButton


class ConversationComposer(QWidget):
    """One bottom surface; Live is the only available way to send a turn."""

    start_requested = Signal()
    stop_requested = Signal()
    mute_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("ConversationComposer { background: transparent; }")
        self._state: str = EngineState.IDLE
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 18)
        layout.setSpacing(12)
        self._surface = QFrame()
        self._surface.setObjectName("conversationComposer")
        layout.addWidget(self._surface)
        inner = QHBoxLayout(self._surface)
        self._inner = inner
        inner.setContentsMargins(8, 8, 8, 8)
        inner.setSpacing(6)
        inner.addStretch(0)

        self._attachment_button = self._future_button("Add photos or attachments — coming soon")
        inner.addWidget(self._attachment_button)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Message RoomKit…")
        self._input.setAccessibleName("Message RoomKit — coming soon")
        self._input.setAccessibleDescription("Text input is coming soon. Use Live to talk.")
        self._input.setToolTip("Text input is coming soon. Use Live to talk.")
        self._input.setReadOnly(True)
        self._input.setEnabled(False)
        self._input.setFocusPolicy(Qt.NoFocus)
        self._input.setMinimumHeight(30)
        self._input.setStyleSheet(
            "QLineEdit { background: transparent; border: none; padding: 0 4px; font-size: 15px; }"
        )
        inner.addWidget(self._input, 1)

        self._dictation_button = self._future_button("Dictate a message — coming soon")
        inner.addWidget(self._dictation_button)

        self._mute_button = KeyboardButton()
        self._mute_button.setCheckable(True)
        self._mute_button.setFixedSize(56, 56)
        self._mute_button.setIconSize(QSize(24, 24))
        self._mute_button.setCursor(Qt.PointingHandCursor)
        self._mute_button.toggled.connect(self._on_mute)
        inner.addWidget(self._mute_button)

        self._live_button = KeyboardButton()
        self._live_button.setFixedSize(44, 44)
        self._live_button.setIconSize(QSize(20, 20))
        self._live_button.setCursor(Qt.PointingHandCursor)
        self._live_button.clicked.connect(self._on_action)
        inner.addWidget(self._live_button)
        inner.addStretch(0)
        bind_theme(self, self._refresh)

    @staticmethod
    def _future_button(name: str) -> KeyboardButton:
        button = KeyboardButton()
        button.setFixedSize(36, 36)
        button.setIconSize(QSize(20, 20))
        button.setAccessibleName(name)
        button.setToolTip(name)
        button.setEnabled(False)
        button.setFocusPolicy(Qt.NoFocus)
        button.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")
        return button

    def set_state(self, state: str) -> None:
        self._state = state
        if state in (EngineState.IDLE, EngineState.ERROR):
            # The engine resets mute on teardown. Reflect it without sending
            # a second mute command during the state-change callback.
            self._mute_button.blockSignals(True)
            self._mute_button.setChecked(False)
            self._mute_button.blockSignals(False)
        self._refresh()

    def _refresh(self) -> None:
        c = colors()
        live = self._state == EngineState.ACTIVE
        connecting = self._state == EngineState.CONNECTING
        stopping = self._state == EngineState.STOPPING
        busy = live or connecting or stopping
        muted = self._mute_button.isChecked()
        self._surface.setStyleSheet(
            "QFrame#conversationComposer { background: transparent; border: none; }"
            if busy
            else (
                "QFrame#conversationComposer {"
                f" background: {c['BG_SECONDARY']}; border: 1px solid {c['BG_TERTIARY']};"
                " border-radius: 24px; }"
            )
        )
        self._inner.setSpacing(20 if busy else 6)
        self._inner.setStretch(0, 1 if busy else 0)
        self._inner.setStretch(self._inner.count() - 1, 1 if busy else 0)
        if connecting or stopping:
            self._live_button.setFixedSize(128, 44)
        else:
            self._live_button.setFixedSize(56 if live else 44, 56 if live else 44)
        self._live_button.setText("Cancel" if connecting else "Ending…" if stopping else "")
        self._live_button.setIconSize(QSize(24 if busy else 20, 24 if busy else 20))

        name, glyph = "Start a live conversation", "waveform"
        if connecting:
            name, glyph = "Cancel connection", "stop"
        elif live:
            name, glyph = "End live conversation", "phone-x-mark"
        elif stopping:
            name, glyph = "Ending live conversation", "stop"
        self._live_button.setAccessibleName(name)
        self._live_button.setToolTip(name)
        self._live_button.setEnabled(not stopping)
        accent = c["ACCENT_RED"] if live else c["ACCENT_BRAND"]
        foreground = "#FFFFFF" if live else c["BG_PRIMARY"]
        if connecting or stopping:
            accent, foreground = c["BG_SECONDARY"], c["TEXT_PRIMARY"]
        self._live_button.setIcon(svg_icon(glyph, foreground, 24 if busy else 20))
        self._live_button.setStyleSheet(
            "QPushButton {"
            f" background: {accent}; color: {foreground}; border: 2px solid transparent;"
            f" border-radius: {28 if live else 22}px; padding: 0; }}"
            f"QPushButton:hover {{ border-color: {c['TEXT_PRIMARY']}; }}"
            'QPushButton[keyboardFocus="true"] {'
            f" border-color: {c['TEXT_PRIMARY']}; }}"
            f"QPushButton:disabled {{ background: {c['BG_TERTIARY']};"
            f" color: {c['TEXT_SECONDARY']}; }}"
        )
        self._input.setVisible(not busy)
        self._attachment_button.setVisible(not busy)
        self._dictation_button.setVisible(not busy)
        self._attachment_button.setIcon(svg_icon("plus", c["TEXT_SECONDARY"], 20))
        self._dictation_button.setIcon(svg_icon("microphone", c["TEXT_SECONDARY"], 20))
        self._mute_button.setVisible(live)
        self._mute_button.setEnabled(live)
        mute_name = "Unmute microphone" if muted else "Mute microphone"
        self._mute_button.setAccessibleName(mute_name)
        self._mute_button.setToolTip(mute_name)
        self._mute_button.setIcon(
            svg_icon(
                "microphone-slash" if muted else "microphone",
                c["ACCENT_RED"] if muted else c["TEXT_PRIMARY"],
                24,
            )
        )
        self._mute_button.setStyleSheet(
            f"QPushButton {{ background: {c['BG_SECONDARY']};"
            f" border: 1px solid {c['BG_TERTIARY']};"
            " border-radius: 28px; padding: 0; }"
            f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
            f"QPushButton:checked {{ border-color: {c['ACCENT_RED']}; }}"
            'QPushButton[keyboardFocus="true"] {'
            f" border-color: {c['ACCENT_BRAND']}; }}"
        )
        palette = self._input.palette()
        palette.setColor(QPalette.PlaceholderText, QColor(c["TEXT_SECONDARY"]))
        self._input.setPalette(palette)

    def _on_action(self) -> None:
        if self._state in (EngineState.ACTIVE, EngineState.CONNECTING):
            self.stop_requested.emit()
        elif self._state in (EngineState.IDLE, EngineState.ERROR):
            self.start_requested.emit()

    def _on_mute(self, muted: bool) -> None:
        self._refresh()
        self.mute_toggled.emit(muted)
