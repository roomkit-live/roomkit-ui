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

from roomkit_ui.theme import colors
from roomkit_ui.widgets.chat_bubble import ChatBubble


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
        self._loading_label: QLabel | None = None

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

    def add_transcription(
        self, text: str, role: str, is_final: bool, speaker_name: str = ""
    ) -> None:
        """Add or update a chat bubble from a transcription event.

        Partials (is_final=False) replace the current bubble text.
        For assistant partials, a word-by-word streaming animation is used.
        Finals replace and freeze the bubble (renders markdown for assistant).
        """
        self._hide_status()

        if (
            self._current_bubble is not None
            and not self._current_bubble.finalized
            and self._current_bubble.role == role
        ):
            self._current_bubble.set_text(text)
            # Update speaker label when diarization catches up mid-utterance
            if speaker_name and speaker_name != self._current_bubble._speaker_name:
                self._current_bubble.set_speaker_name(speaker_name)
        else:
            # New bubble (finalize any previous in-progress bubble first)
            if self._current_bubble and not self._current_bubble.finalized:
                # Same utterance re-classified by diarization (user↔other):
                # replace the old bubble instead of keeping both.
                if self._current_bubble.role in ("user", "other") and role in (
                    "user",
                    "other",
                ):
                    self._layout.removeWidget(self._current_bubble)
                    self._current_bubble.deleteLater()
                    self._current_bubble = None
                else:
                    self._current_bubble.finalize()
            if not is_final and role == "assistant":
                # Create empty bubble then stream words in
                bubble = ChatBubble("", role=role, speaker_name=speaker_name)
            else:
                bubble = ChatBubble(text, role=role, speaker_name=speaker_name)
            # Insert before status_label (last widget) and stretch (second-to-last)
            idx = self._layout.count() - 2
            if idx < 0:
                idx = 0
            self._layout.insertWidget(idx, bubble)
            self._current_bubble = bubble
            if not is_final and role == "assistant":
                bubble.start_streaming(text)
                bubble._stream_timer.timeout.connect(self._scroll_to_bottom)

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

    def set_loading_status(self, message: str) -> None:
        """Show or update a single loading status label (replaces previous)."""
        c = colors()
        if self._loading_label is None:
            self._loading_label = QLabel()
            self._loading_label.setWordWrap(True)
            self._loading_label.setAlignment(Qt.AlignCenter)
            self._loading_label.setStyleSheet(
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
            self._layout.insertWidget(idx, self._loading_label)
        self._loading_label.setText(message)
        self._scroll_to_bottom()

    def clear_loading_status(self) -> None:
        """Remove the loading status label if present."""
        if self._loading_label is not None:
            self._layout.removeWidget(self._loading_label)
            self._loading_label.deleteLater()
            self._loading_label = None

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

    def add_app_tool_call(
        self,
        tool_name: str,
        arguments_json: str,
        html_content: str | None,
        server_name: str,
    ) -> QWidget | None:
        """Embed an MCP App widget in the chat, or fall back to a text label.

        Returns the ``MCPAppWidget`` if created, else ``None``.
        """
        from roomkit_ui.widgets.mcp_app_widget import MCPAppWidget, has_webengine

        if html_content is None or not has_webengine():
            self.add_tool_call(tool_name, arguments_json)
            return None

        self._hide_status()
        if self._current_bubble and not self._current_bubble.finalized:
            self._current_bubble.finalize()
            self._current_bubble = None

        widget = MCPAppWidget(tool_name, server_name, parent=self._container)
        widget.load_html(html_content)

        idx = self._layout.count() - 2
        if idx < 0:
            idx = 0
        self._layout.insertWidget(idx, widget)
        self._scroll_to_bottom()
        return widget

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
        self._loading_label = None
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
        self._loading_label = None
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
