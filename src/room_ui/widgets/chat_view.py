"""Scrollable chat area with bubble widgets and speaking indicators."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from room_ui.theme import colors
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
        self._layout.addStretch()  # index 0: pushes content down
        self.setWidget(self._container)

        self._current_bubble: ChatBubble | None = None

        c = colors()

        # Empty state (shown before conversation starts, centered vertically)
        self._empty_state = QWidget()
        self._empty_state.setStyleSheet("background: transparent;")
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(20)

        icon = QLabel()
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("background: transparent;")
        logo_path = Path(__file__).resolve().parent.parent / "assets" / "logo.svg"
        if logo_path.exists():
            svg_data = QByteArray(logo_path.read_bytes())
            renderer = QSvgRenderer(svg_data)
            pixmap = QPixmap(64, 64)
            pixmap.fill(QColor(0, 0, 0, 0))
            from PySide6.QtGui import QPainter

            painter = QPainter(pixmap)
            renderer.render(painter, QRectF(0, 0, 64, 64))
            painter.end()
            icon.setPixmap(pixmap)
        else:
            icon.setText("\U0001f399")
            icon.setStyleSheet("font-size: 48px; background: transparent;")
        empty_layout.addWidget(icon)

        heading = QLabel("RoomKit UI")
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet(
            f"font-size: 18px; font-weight: 600;"
            f" color: {c['TEXT_PRIMARY']}; background: transparent;"
        )
        empty_layout.addWidget(heading)

        hint = QLabel("Press Start to begin a voice conversation")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            f"font-size: 15px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        empty_layout.addWidget(hint)

        # Center the empty state: stretch - widget - stretch
        self._layout.insertWidget(1, self._empty_state)
        self._layout.addStretch()  # bottom stretch for centering

        # Status indicator (Listening… / Thinking…)
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet(
            f"QLabel {{ color: {c['TEXT_SECONDARY']}; font-size: 12px; font-style: italic;"
            f" background: transparent; padding: 4px; }}"
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

    def add_info(self, message: str) -> None:
        """Show a neutral info message in the chat area."""
        self._hide_status()
        if self._current_bubble and not self._current_bubble.finalized:
            self._current_bubble.finalize()
            self._current_bubble = None

        c = colors()
        label = QLabel(message)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"QLabel {{"
            f"  color: {c['TEXT_SECONDARY']};"
            f"  font-size: 12px;"
            f"  background: {c['BG_TERTIARY']};"
            f"  border: 1px solid {c['SEPARATOR']};"
            f"  border-radius: 8px;"
            f"  padding: 8px 16px;"
            f"  margin: 4px 20px;"
            f"}}"
        )
        idx = self._layout.count() - 2
        if idx < 0:
            idx = 0
        self._layout.insertWidget(idx, label)
        self._scroll_to_bottom()

    def add_tool_call(self, name: str, arguments: str) -> None:
        """Show a tool-call indicator in the chat area."""
        self._hide_status()
        if self._current_bubble and not self._current_bubble.finalized:
            self._current_bubble.finalize()
            self._current_bubble = None

        c = colors()
        label = QLabel(f"\u2699  {name}({arguments})")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"QLabel {{"
            f"  color: #BF5AF2;"
            f"  font-size: 12px;"
            f"  background: {c['BG_TERTIARY']};"
            f"  border: 1px solid {c['SEPARATOR']};"
            f"  border-radius: 8px;"
            f"  padding: 8px 16px;"
            f"  margin: 4px 20px;"
            f"}}"
        )
        idx = self._layout.count() - 2
        if idx < 0:
            idx = 0
        self._layout.insertWidget(idx, label)
        self._scroll_to_bottom()

    def add_error(self, message: str) -> None:
        """Show a centered error message in the chat area."""
        self._hide_status()
        if self._current_bubble and not self._current_bubble.finalized:
            self._current_bubble.finalize()
            self._current_bubble = None

        c = colors()
        label = QLabel(message)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"QLabel {{"
            f"  color: {c['ACCENT_RED']};"
            f"  font-size: 12px;"
            f"  background: {c['BG_TERTIARY']};"
            f"  border: 1px solid {c['SEPARATOR']};"
            f"  border-radius: 8px;"
            f"  padding: 8px 16px;"
            f"  margin: 4px 20px;"
            f"}}"
        )
        idx = self._layout.count() - 2
        if idx < 0:
            idx = 0
        self._layout.insertWidget(idx, label)
        self._scroll_to_bottom()

    def clear(self) -> None:
        """Remove all bubbles and error labels, switch to chat layout."""
        self._empty_state.hide()
        # Remove everything from layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w and w not in (self._empty_state, self._status_label):
                w.deleteLater()
        # Rebuild base layout: stretch (pushes to bottom) + status_label
        self._layout.addStretch()
        self._layout.addWidget(self._status_label)
        self._current_bubble = None

    def reset(self) -> None:
        """Clear conversation and show empty state again."""
        self._hide_status()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w and w not in (self._empty_state, self._status_label):
                w.deleteLater()
        self._current_bubble = None
        # Rebuild with empty state centered
        self._layout.addStretch()
        self._layout.insertWidget(1, self._empty_state)
        self._layout.addStretch()
        self._layout.addWidget(self._status_label)
        self._empty_state.show()

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
        QTimer.singleShot(
            10, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
        )
