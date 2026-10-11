"""Scrollable chat area with bubble widgets and speaking indicators."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme_live import themed_style
from roomkit_ui.widgets.chat_bubble import ChatBubble

# Entrance fade for new rows (bubbles, tool/info pills).
_FADE_IN_MS = 220


def _fade_in(widget: QWidget) -> None:
    """Fade a freshly inserted row from transparent to opaque.

    The opacity effect is removed once the animation lands: leaving it in
    place costs an offscreen render pass per paint — noticeable under the
    software renderer this app often runs on — and can subtly change text
    antialiasing.  The animation is parented to the widget so an early
    row teardown (diarization re-classifying a bubble) tears it down too.
    """
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(_FADE_IN_MS)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    # None removes the effect — valid Qt, but the stubs disagree.
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))  # type: ignore[arg-type]
    anim.start(QPropertyAnimation.DeleteWhenStopped)


class ChatView(QScrollArea):
    """Scrollable chat transcript with iMessage-style bubbles."""

    # A plain click on the name of a voice the STT tells apart ("Speaker B").
    speaker_clicked = Signal(str)

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

        # The user's turn being heard, and the assistant's reply being said:
        # one may open while the other still runs (the user speaks over the
        # reply), and each keeps its own entry.
        self._current_bubble: ChatBubble | None = None
        self._reply: ChatBubble | None = None
        # The session's nameable voices ("Speaker B") → what they are called.
        self._voice_names: dict[str, str] = {}
        # The last assistant entry, tracked past its final: a graceful
        # finalize keeps revealing after _reply is released, and
        # a barge-in must be able to snap that reveal short.
        self._last_assistant_bubble: ChatBubble | None = None
        self._loading_label: QLabel | None = None

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
        themed_style(
            heading,
            lambda c: (
                f"font-size: 18px; font-weight: 600;"
                f" color: {c['TEXT_PRIMARY']}; background: transparent;"
            ),
        )
        empty_layout.addWidget(heading)

        hint = QLabel("Press Start to begin a voice conversation")
        hint.setAlignment(Qt.AlignCenter)
        themed_style(
            hint,
            lambda c: f"font-size: 15px; color: {c['TEXT_SECONDARY']}; background: transparent;",
        )
        empty_layout.addWidget(hint)

        # Center the empty state: stretch - widget - stretch
        self._layout.insertWidget(1, self._empty_state)
        self._layout.addStretch()  # bottom stretch for centering

        # Status indicator (Listening… / Thinking…)
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        themed_style(
            self._status_label,
            lambda c: (
                f"QLabel {{ color: {c['TEXT_SECONDARY']}; font-size: 12px; font-style: italic;"
                f" background: transparent; padding: 4px; }}"
            ),
        )
        self._status_label.hide()
        self._layout.addWidget(self._status_label)

        # Pulse animation for status indicator
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(500)
        self._pulse_dots = 0
        self._pulse_base = ""
        self._pulse_timer.timeout.connect(self._pulse_tick)

        # Reusable single-shot timer for scroll-to-bottom — avoids creating
        # a new QTimer on every streaming tick (~25/sec during responses).
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(10)
        self._scroll_timer.timeout.connect(self._do_scroll)

        # Auto-follow: a growing bubble updates the scroll range AFTER the
        # 10 ms timer fired, leaving the view stuck one line above the
        # bottom.  rangeChanged fires after every layout pass — the only
        # reliable moment to jump.  The flag disengages when the user
        # scrolls up to read history and re-engages at the bottom.
        self._autoscroll = True
        sb = self.verticalScrollBar()
        sb.rangeChanged.connect(self._on_scroll_range_changed)
        sb.valueChanged.connect(self._on_scroll_value_changed)

    # -- public API ----------------------------------------------------------

    def add_transcription(
        self, text: str, role: str, is_final: bool, speaker_name: str = ""
    ) -> None:
        """Add or update a chat bubble from a transcription event.

        Partials (is_final=False) replace the current bubble text.
        For assistant partials, a word-by-word streaming animation is used.
        Finals replace and freeze the bubble (renders markdown for assistant).

        The user's speech does not end the reply being said: with barge-in
        off, or for an "ok", the voice goes on, and the reply's later words
        and its final land in its own entry.  Only interrupt_reply() cuts it.
        """
        self._hide_status()
        if role == "assistant":
            self._add_reply_text(text, is_final, speaker_name)
        else:
            self._add_turn_text(text, role, is_final, speaker_name)
        self._scroll_to_bottom()

    def interrupt_reply(self, heard_ms: int = -1) -> None:
        """roomkit cut the assistant's voice: its reply keeps what was said,
        marked as cut short, and its next words open a new entry.

        *heard_ms* is how much of the reply played, -1 when unknown (see
        ChatBubble.cut_short).  The reply may still be open, or have had its
        final while its words are still revealing.  A reply fully shown is
        left as it is.
        """
        reply = self._reply or self._last_assistant_bubble
        self._reply = None
        if reply is not None and not reply.finalized:
            reply.cut_short(heard_ms)

    def _add_reply_text(self, text: str, is_final: bool, speaker_name: str) -> None:
        reply = self._reply
        if reply is None:
            # Always stream assistant text — a provider that hands the
            # full transcript at once (Grok, OpenAI) still rolls out.
            reply = ChatBubble("", role="assistant", speaker_name=speaker_name)
            self._insert_bubble(reply)
            self._reply = self._last_assistant_bubble = reply
            reply.start_streaming(text)
            reply.streaming_tick.connect(self._scroll_to_bottom)
        else:
            # Keep the word reveal rolling — set_text would snap the
            # whole update into place and kill the pacing.
            reply.update_stream(text)
        if is_final:
            reply.finalize()
            self._reply = None

    def _add_turn_text(self, text: str, role: str, is_final: bool, speaker_name: str) -> None:
        turn = self._current_bubble
        if turn is not None and turn.role == role:
            turn.set_text(text)
            # Update speaker label when diarization catches up mid-utterance
            if speaker_name:
                self._label_bubble(turn, speaker_name)
        else:
            if turn is not None:
                # Same utterance re-classified by diarization (user↔other):
                # replace the old bubble instead of keeping both.
                self._layout.removeWidget(turn)
                turn.deleteLater()
            turn = ChatBubble(text, role=role)
            # Only a nameable voice's label is clickable (_label_bubble).
            turn.speaker_clicked.connect(lambda b=turn: self.speaker_clicked.emit(b.voice))
            self._label_bubble(turn, speaker_name)
            self._insert_bubble(turn)
            self._current_bubble = turn
        if is_final:
            turn.finalize()
            self._current_bubble = None

    def _insert_bubble(self, bubble: ChatBubble) -> None:
        # Insert before status_label (last widget) and stretch (second-to-last)
        idx = max(self._layout.count() - 2, 0)
        self._layout.insertWidget(idx, bubble)
        _fade_in(bubble)

    def name_voice(self, voice: str, name: str) -> None:
        """A voice the STT tells apart is now called *name*: its turns, past
        and to come, show it, and a click on it can rename it."""
        self._voice_names[voice] = name
        for bubble in self._bubbles():
            if bubble.voice == voice:
                self._label_bubble(bubble, voice)

    def voice_name(self, voice: str) -> str:
        """What a voice is called now: its name, else its label."""
        return self._voice_names.get(voice, voice)

    def given_names(self) -> list[str]:
        """The names given to the session's voices, each once."""
        names = [name for voice, name in self._voice_names.items() if name != voice]
        return list(dict.fromkeys(names))

    def _label_bubble(self, bubble: ChatBubble, speaker: str) -> None:
        """Show *speaker* on a user-side bubble: by its name when it is a
        nameable voice, which a plain click then names."""
        nameable = speaker in self._voice_names
        bubble.voice = speaker if nameable else ""
        bubble.set_speaker_name(self._voice_names.get(speaker, speaker))
        bubble.set_speaker_clickable(nameable)

    def _bubbles(self) -> list[ChatBubble]:
        bubbles: list[ChatBubble] = []
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, ChatBubble):
                bubbles.append(widget)
        return bubbles

    def show_listening(self) -> None:
        self._show_status("Listening")

    def show_thinking(self) -> None:
        self._show_status("Thinking")

    def hide_status(self) -> None:
        self._hide_status()

    def _make_status_label(self, text: str, color: str) -> QLabel:
        """Quiet inline note shared by loading/info/tool/error rows.

        Left-aligned muted text in the flow of the conversation — the way
        modern AI chats surface "tools loaded, web searched" — rather than
        a centered pill that interrupts it.
        """
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignLeft)
        themed_style(
            label,
            lambda c: (
                f"QLabel {{"
                f"  color: {c.get(color, color)};"
                f"  font-size: 12px;"
                f"  background: transparent;"
                f"  padding: 2px 24px;"
                f"}}"
            ),
        )
        return label

    def _insert_status_row(self, widget: QWidget) -> None:
        """Insert a widget above the bottom status area and scroll."""
        idx = self._layout.count() - 2
        if idx < 0:
            idx = 0
        self._layout.insertWidget(idx, widget)
        _fade_in(widget)
        self._scroll_to_bottom()

    def _finalize_current_bubble(self) -> None:
        self._hide_status()
        for bubble in (self._current_bubble, self._reply):
            if bubble is not None and not bubble.finalized:
                bubble.finalize()
        self._current_bubble = None
        self._reply = None

    def set_loading_status(self, message: str) -> None:
        """Show or update a single loading status label (replaces previous)."""
        if self._loading_label is None:
            self._loading_label = self._make_status_label("", "TEXT_SECONDARY")
            self._insert_status_row(self._loading_label)
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
        self._finalize_current_bubble()
        self._insert_status_row(self._make_status_label(message, "TEXT_SECONDARY"))

    def add_tool_call(self, name: str, arguments: str) -> None:
        """Show a tool-call indicator in the chat area."""
        self._finalize_current_bubble()
        self._insert_status_row(self._make_status_label(f"\u2699  {name}({arguments})", "#BF5AF2"))

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

        self._finalize_current_bubble()

        widget = MCPAppWidget(tool_name, server_name, parent=self._container)
        widget.load_html(html_content)
        self._insert_status_row(widget)
        return widget

    def add_install_offer(self, feature: str) -> None:
        """A session that could not start for want of a component: what is
        missing, and the button that adds it."""
        from roomkit_ui.features import FEATURES
        from roomkit_ui.widgets.install_offer import InstallOffer

        self._finalize_current_bubble()
        offer = InstallOffer(color="ACCENT_RED", done_hint="Start the session again.")
        label = FEATURES[feature].label
        offer.set_feature(feature, text=f"The session could not start: {label} is not installed.")
        offer.setContentsMargins(14, 2, 14, 2)
        self._insert_status_row(offer)

    def add_error(self, message: str) -> None:
        """Show a centered error message in the chat area."""
        self._finalize_current_bubble()
        self._insert_status_row(self._make_status_label(message, "ACCENT_RED"))

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
                # Finalize streaming bubbles to stop their timers before deletion
                if isinstance(w, ChatBubble) and not w.finalized:
                    # Interrupted-style: snaps any pending reveal so its
                    # timer cannot outlive the widget (no marker shown on
                    # a bubble that is being deleted anyway).
                    w.finalize(interrupted=True)
                w.deleteLater()
        # Rebuild base layout: stretch (pushes to bottom) + status_label
        self._layout.addStretch()
        self._layout.addWidget(self._status_label)
        self._current_bubble = None
        self._reply = None
        self._last_assistant_bubble = None
        self._voice_names.clear()

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
                if isinstance(w, ChatBubble) and not w.finalized:
                    w.finalize()
                w.deleteLater()
        self._current_bubble = None
        self._reply = None
        self._last_assistant_bubble = None  # deleted above, like every bubble
        self._voice_names.clear()
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
        self._scroll_timer.start()  # restarts if already running

    def _do_scroll(self) -> None:
        if self._autoscroll:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def _on_scroll_value_changed(self, value: int) -> None:
        self._autoscroll = value >= self.verticalScrollBar().maximum() - 4

    def _on_scroll_range_changed(self, _lo: int, _hi: int) -> None:
        if self._autoscroll:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
