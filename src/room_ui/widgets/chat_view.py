"""Scrollable chat area with bubble widgets and speaking indicators."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from room_ui.widgets.chat_bubble import ChatBubble


class ChatView(QScrollArea):
    """Scrollable chat transcript with iMessage-style bubbles."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 8, 4, 8)
        self._layout.setSpacing(4)
        self._layout.addStretch()  # pushes bubbles to the bottom
        self.setWidget(self._container)

        self._current_bubble: ChatBubble | None = None

        # Status indicator (Listening… / Thinking…)
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet(
            "QLabel { color: #8E8E93; font-size: 12px; font-style: italic;"
            " background: transparent; padding: 4px; }"
        )
        self._status_label.hide()
        self._layout.addWidget(self._status_label)

        # Pulse animation for status indicator
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(500)
        self._pulse_dots = 0
        self._pulse_base = ""
        self._pulse_timer.timeout.connect(self._pulse_tick)

    # -- public API ----------------------------------------------------------

    def add_transcription(self, text: str, role: str, is_final: bool) -> None:
        """Add or update a chat bubble from a transcription event.

        Partials (is_final=False) are word fragments that get appended to the
        current in-progress bubble.  Finals replace the bubble text with the
        complete sentence and freeze it.
        """
        self._hide_status()

        if (
            self._current_bubble is not None
            and not self._current_bubble.finalized
            and self._current_bubble.role == role
        ):
            if is_final:
                # Final replaces with the complete text
                self._current_bubble.set_text(text)
            else:
                # Partial — append the fragment
                self._current_bubble.append_text(text)
        else:
            # New bubble (finalize any previous in-progress bubble first)
            if self._current_bubble and not self._current_bubble.finalized:
                self._current_bubble.finalize()
            bubble = ChatBubble(text, role=role)
            # Insert before status_label (last widget) and stretch (second-to-last)
            idx = self._layout.count() - 2
            if idx < 0:
                idx = 0
            self._layout.insertWidget(idx, bubble)
            self._current_bubble = bubble

        if is_final:
            self._current_bubble.finalize()
            self._current_bubble = None

        self._scroll_to_bottom()

    def show_listening(self) -> None:
        self._show_status("Listening")

    def show_thinking(self) -> None:
        self._show_status("Thinking")

    def hide_status(self) -> None:
        self._hide_status()

    def add_error(self, message: str) -> None:
        """Show a centered error message in the chat area."""
        self._hide_status()
        if self._current_bubble and not self._current_bubble.finalized:
            self._current_bubble.finalize()
            self._current_bubble = None

        label = QLabel(message)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            "QLabel {"
            "  color: #FF453A;"
            "  font-size: 12px;"
            "  background: rgba(255, 69, 58, 0.1);"
            "  border-radius: 8px;"
            "  padding: 8px 16px;"
            "  margin: 4px 20px;"
            "}"
        )
        idx = self._layout.count() - 2
        if idx < 0:
            idx = 0
        self._layout.insertWidget(idx, label)
        self._scroll_to_bottom()

    def clear(self) -> None:
        """Remove all bubbles and error labels."""
        while self._layout.count() > 2:  # keep stretch + status_label
            item = self._layout.takeAt(0)
            w = item.widget()
            if w and isinstance(w, (ChatBubble, QLabel)):
                w.deleteLater()
        self._current_bubble = None

    # -- internal ------------------------------------------------------------

    def _show_status(self, text: str) -> None:
        self._pulse_base = text
        self._pulse_dots = 0
        self._status_label.setText(text + "...")
        self._status_label.show()
        self._pulse_timer.start()
        self._scroll_to_bottom()

    def _hide_status(self) -> None:
        self._pulse_timer.stop()
        self._status_label.hide()

    def _pulse_tick(self) -> None:
        self._pulse_dots = (self._pulse_dots + 1) % 4
        dots = "." * (self._pulse_dots + 1)
        self._status_label.setText(self._pulse_base + dots)

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(10, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))
