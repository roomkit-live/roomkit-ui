"""Growing text composer and Live controls on the same surface."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPalette, QTextLayout
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.engine_state import EngineState
from roomkit_ui.icons import svg_icon
from roomkit_ui.text_chat import CONFIGURATION_HINT
from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.widgets.buttons import KeyboardButton
from roomkit_ui.widgets.message_input import MessageInput


class ConversationComposer(QWidget):
    """Send typed turns when configured, or open Live with an empty draft."""

    start_requested = Signal()
    send_requested = Signal(str)
    stop_requested = Signal()
    mute_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("ConversationComposer { background: transparent; }")
        self._state: str = EngineState.IDLE
        self._text_mode = False
        self._expanded = False
        self._voice_controls = False
        self._unavailable = "Configure a chat model in Settings…"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 18)
        layout.setSpacing(12)
        self._surface = QFrame()
        self._surface.setObjectName("conversationComposer")
        layout.addWidget(self._surface)
        self._stack = QVBoxLayout(self._surface)
        self._stack.setContentsMargins(8, 8, 8, 8)
        self._stack.setSpacing(6)
        inner = QHBoxLayout()
        self._inner = inner
        self._stack.addLayout(inner)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(6)
        inner.addStretch(0)

        self._attachment_button = self._future_button("Add photos or attachments — coming soon")
        inner.addWidget(self._attachment_button, 0, Qt.AlignBottom)

        self._input = MessageInput()
        self._input.setAccessibleName("Message RoomKit")
        self._input.textChanged.connect(self._refresh)
        self._input.send_requested.connect(self._send)
        inner.addWidget(self._input, 1)

        self._dictation_button = self._future_button("Dictate a message — coming soon")
        inner.addWidget(self._dictation_button, 0, Qt.AlignBottom)

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
        inner.addWidget(self._live_button, 0, Qt.AlignBottom)
        inner.addStretch(0)
        bind_theme(self, self._refresh)

    @staticmethod
    def _future_button(name: str) -> KeyboardButton:
        button = KeyboardButton()
        button.setFixedSize(36, 44)
        button.setIconSize(QSize(20, 20))
        button.setAccessibleName(name)
        button.setToolTip(name)
        button.setEnabled(False)
        button.setFocusPolicy(Qt.NoFocus)
        button.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")
        return button

    def set_text_availability(self, reason: str) -> None:
        self._unavailable = reason
        self._refresh()

    def clear_draft(self) -> None:
        self._input.clear()

    def focus_input(self) -> None:
        if self._input.isEnabled() and not self._input.isHidden():
            self._input.setFocus()

    def _arrange_input(self) -> None:
        # Measure against the compact row even while expanded: measuring the
        # wider editor itself would alternate between the two layouts on wrap.
        margins = self._stack.contentsMargins()
        width = float(self._surface.contentsRect().width() - margins.left() - margins.right())
        width -= sum(
            button.width()
            for button in (self._attachment_button, self._dictation_button, self._live_button)
        )
        width -= 3 * 6 + 2 * self._input.document().documentMargin()
        text = self._input.toPlainText()
        expanded = False
        if text and not self._voice_controls:
            # Shift+Enter adds a line separator within the same Qt block.
            # toPlainText normalizes it to a newline, just like pasted breaks.
            if "\n" in text:
                expanded = True
            else:
                measure = QTextLayout(text, self._input.font())
                measure.setTextOption(self._input.document().defaultTextOption())
                measure.beginLayout()
                line = measure.createLine()
                line.setLineWidth(max(1, width))
                expanded = measure.createLine().isValid()
                measure.endLayout()
        if expanded == self._expanded:
            return
        self._expanded = expanded
        if expanded:
            self._inner.removeWidget(self._input)
            self._inner.insertStretch(2, 1)
            self._stack.insertWidget(0, self._input)
        else:
            self._stack.removeWidget(self._input)
            self._inner.takeAt(2)  # The spacer used by the expanded action row.
            self._inner.insertWidget(2, self._input, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._arrange_input()

    def set_state(self, state: str, *, text_mode: bool = False) -> None:
        self._state = state
        self._text_mode = text_mode
        if state in (EngineState.IDLE, EngineState.ERROR, EngineState.READY):
            # The engine resets mute on teardown. Reflect it without sending
            # a second mute command during the state-change callback.
            self._mute_button.blockSignals(True)
            self._mute_button.setChecked(False)
            self._mute_button.blockSignals(False)
        self._refresh()

    def _refresh(self) -> None:
        c = colors()
        text_busy = self._text_mode and self._state not in (
            EngineState.IDLE,
            EngineState.ERROR,
            EngineState.READY,
        )
        live = not self._text_mode and self._state == EngineState.ACTIVE
        connecting = not self._text_mode and self._state == EngineState.CONNECTING
        stopping = self._state == EngineState.STOPPING
        busy = not self._text_mode and (live or connecting or stopping)
        self._voice_controls = busy
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
        if busy and (connecting or stopping):
            self._live_button.setFixedSize(128, 44)
        else:
            self._live_button.setFixedSize(56 if live else 44, 56 if live else 44)
        self._live_button.setText(
            "Cancel" if connecting else "Ending…" if busy and stopping else ""
        )
        self._live_button.setIconSize(QSize(24 if busy else 20, 24 if busy else 20))

        name, glyph = "Start a live conversation", "waveform"
        if connecting:
            name, glyph = "Cancel connection", "stop"
        elif live:
            name, glyph = "End live conversation", "phone-x-mark"
        elif stopping:
            name, glyph = "Ending live conversation", "stop"
        if text_busy:
            name, glyph = "Stopping response" if stopping else "Stop response", "stop"
        elif not busy and not self._unavailable and self._input.toPlainText().strip():
            name, glyph = "Send message", "arrow-up"
        self._live_button.setAccessibleName(name)
        self._live_button.setToolTip(name)
        self._live_button.setEnabled(not stopping)
        accent = c["ACCENT_RED"] if live else c["ACCENT_BRAND"]
        foreground = "#FFFFFF" if live else c["BG_PRIMARY"]
        if busy and (connecting or stopping):
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
        ready = not self._unavailable
        self._input.setEnabled(ready)
        self._input.setReadOnly(not ready)
        self._input.setFocusPolicy(Qt.StrongFocus if ready else Qt.NoFocus)
        self._input.setPlaceholderText(
            "Configure chat in Settings…" if self._unavailable else "Message RoomKit…"
        )
        hint = (
            f"{self._unavailable} {CONFIGURATION_HINT}"
            if self._unavailable
            else "Enter to send · Shift+Enter for a new line"
        )
        self._input.setToolTip(hint)
        self._surface.setToolTip(hint if self._unavailable else "")
        self._input.setAccessibleDescription(hint)
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
        self._arrange_input()

    def _on_action(self) -> None:
        if self._state in (EngineState.ACTIVE, EngineState.CONNECTING):
            self.stop_requested.emit()
            if self._text_mode:
                self.focus_input()
        elif self._state in (EngineState.IDLE, EngineState.ERROR, EngineState.READY):
            if not self._unavailable and self._input.toPlainText().strip():
                self._send()
            else:
                self.start_requested.emit()

    def _send(self) -> None:
        if self._unavailable or self._state not in (
            EngineState.IDLE,
            EngineState.ERROR,
            EngineState.READY,
        ):
            return
        if text := self._input.toPlainText().strip():
            self.send_requested.emit(text)

    def _on_mute(self, muted: bool) -> None:
        self._refresh()
        self.mute_toggled.emit(muted)
