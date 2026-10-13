"""Scrollable conversation; voice activity belongs to the Live controls."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.images import ImageAttachment
from roomkit_ui.mcp_app_state import AppToolResults
from roomkit_ui.theme_live import themed_style
from roomkit_ui.tool_events import ToolCall, ToolResult
from roomkit_ui.widgets.chat_bubble import ChatBubble
from roomkit_ui.widgets.conversation_home import ConversationWelcome, LiveWelcome
from roomkit_ui.widgets.tool_activity import ToolActivity

if TYPE_CHECKING:
    from roomkit_ui.widgets.mcp_app_widget import MCPAppWidget

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
    """User bubbles and open assistant replies, with a quiet Live invitation."""

    # A plain click on the name of a voice the STT tells apart ("Speaker B").
    speaker_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.viewport().setStyleSheet("background: transparent;")

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 8, 4, 8)
        self._layout.setSpacing(12)
        self._layout.addStretch()  # index 0: pushes content down
        self.setWidget(self._container)

        # The user's turn being heard, and the assistant's reply being said:
        # one may open while the other still runs (the user speaks over the
        # reply), and each keeps its own entry.
        self._current_bubble: ChatBubble | None = None
        self._reply: ChatBubble | None = None
        self._text_pending: QLabel | None = None
        # The session's nameable voices ("Speaker B") → what they are called.
        self._voice_names: dict[str, str] = {}
        # The last assistant entry, tracked past its final: a graceful
        # finalize keeps revealing after _reply is released, and
        # a barge-in must be able to snap that reveal short.
        self._last_assistant_bubble: ChatBubble | None = None
        # A spoken reply's text comes whole each time (all its words so far,
        # then its final); a tool row or a notice inside it closes its entry,
        # and the next entry shows only the words after what that one did.
        self._reply_text = ""
        self._reply_shown = ""
        self._tool_calls: dict[str, ToolActivity] = {}

        self._empty_state = ConversationWelcome()
        self._live_empty = LiveWelcome(self._container)
        self._live_empty.hide()

        # Center the empty state: stretch - widget - stretch
        self._layout.insertWidget(1, self._empty_state)
        self._layout.addStretch()  # bottom stretch for centering

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
        if role == "assistant":
            self._add_reply_text(text, is_final, speaker_name)
        else:
            self._add_turn_text(text, role, is_final, speaker_name)
        self._scroll_to_bottom()

    def set_text_pending(self, pending: bool) -> None:
        if self._text_pending is not None:
            self._layout.removeWidget(self._text_pending)
            self._text_pending.deleteLater()
            self._text_pending = None
        if pending:
            self._text_pending = self._make_status_label("Thinking…", "TEXT_SECONDARY")
            self._insert_status_row(self._text_pending)

    def add_image_message(self, text: str, images: tuple[ImageAttachment, ...]) -> None:
        self._finalize_current_bubble()
        bubble = ChatBubble(text, role="user", images=images)
        bubble.finalize()
        self._insert_bubble(bubble)
        self._scroll_to_bottom()

    def add_assistant_images(self, images: tuple[ImageAttachment, ...]) -> None:
        """Images the assistant drew: an entry of their own, where they came,
        between the words of its reply."""
        self._finalize_current_bubble()
        bubble = ChatBubble("", role="assistant", images=images)
        bubble.finalize()
        self._insert_bubble(bubble)
        self._scroll_to_bottom()

    def add_text_reply(self, text: str, is_final: bool) -> None:
        """Show provider deltas immediately, without the voice playback pacing."""
        if not text:
            return
        self.set_text_pending(False)
        if self._reply is None:
            self._reply = self._last_assistant_bubble = ChatBubble("", role="assistant")
            self._insert_bubble(self._reply)
        self._reply.set_text(text)
        if is_final:
            self._reply.finalize()
            self._reply = None
        self._scroll_to_bottom()

    def stop_text_reply(self) -> None:
        """Keep all received text when generation is stopped or fails."""
        self.set_text_pending(False)
        if self._reply is not None:
            self._reply.finalize(interrupted=True)
            self._reply = None

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
        self._end_reply()
        if reply is not None and not reply.finalized:
            reply.cut_short(heard_ms)

    def _add_reply_text(self, text: str, is_final: bool, speaker_name: str) -> None:
        self._reply_text = text
        text = self._unshown(text)
        if not text:
            if is_final:  # every word of it is in the entries before
                self._end_reply()
            return
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
            self._end_reply()

    def _unshown(self, text: str) -> str:
        """*text*, a spoken reply's words so far, less those the entries closed
        inside it show.  Spacing aside (its final keeps segments a blank line
        apart), they are its start; text that does not start so is shown whole."""
        shown = [char for char in self._reply_shown if not char.isspace()]
        if not shown:
            return text
        matched = 0
        for index, char in enumerate(text):
            if char.isspace():
                continue
            if matched == len(shown):
                return text[index:]
            if char != shown[matched]:
                return text
            matched += 1
        return ""

    def _end_reply(self) -> None:
        self._reply_text = self._reply_shown = ""

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
        self._hide_live_prompt()
        self._layout.insertWidget(max(self._layout.count() - 1, 0), bubble)
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
        """Insert a note before the bottom stretch and scroll."""
        self._layout.insertWidget(max(self._layout.count() - 1, 0), widget)
        _fade_in(widget)
        self._scroll_to_bottom()

    def _finalize_current_bubble(self) -> None:
        if self._reply is not None:
            # Closed inside its reply: the reply's next words open an entry
            # of their own, and show only themselves.
            self._reply_shown = self._reply_text
        for bubble in (self._current_bubble, self._reply):
            if bubble is not None and not bubble.finalized:
                bubble.finalize()
        self._current_bubble = None
        self._reply = None

    def add_info(self, message: str) -> None:
        """Show a neutral info message in the chat area."""
        self._finalize_current_bubble()
        self._insert_status_row(self._make_status_label(message, "TEXT_SECONDARY"))

    def add_tool_call(self, call: ToolCall) -> ToolActivity:
        """Insert one compact row, updated by invocation ID when it finishes."""
        if call.id in self._tool_calls:
            return self._tool_calls[call.id]
        self._finalize_current_bubble()
        self._hide_live_prompt()
        row = ToolActivity(call, self._container)
        self._tool_calls[call.id] = row
        self._insert_status_row(row)
        return row

    def tool_call(self, call_id: str) -> ToolActivity | None:
        return self._tool_calls.get(call_id)

    def finish_tool_call(self, result: ToolResult) -> None:
        if row := self.tool_call(result.call_id):
            row.finish(result)

    def snapshot(self) -> list[dict]:
        entries: list[dict] = []
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, (ChatBubble, ToolActivity)):
                entries.append(widget.snapshot())
        return entries

    def restore(self, entries: list[dict]) -> None:
        self.clear()
        for entry in entries:
            if entry.get("kind") == "message":
                bubble = ChatBubble(
                    entry["text"], role=entry["role"], speaker_name=entry.get("speaker", "")
                )
                bubble.restore(entry)
                self._hide_live_prompt()
                self._layout.insertWidget(max(self._layout.count() - 1, 0), bubble)
            elif entry.get("kind") == "tool":
                call = ToolCall(**entry["call"])
                row = self.add_tool_call(call)
                row.app_results = AppToolResults.restore(entry.get("app_results", []))
                result = entry.get("result")
                row.finish(
                    ToolResult(**result)
                    if result
                    else ToolResult(
                        call.id, "cancelled", "This call ended before its result was saved."
                    )
                )
                self.attach_app(call.id, entry.get("app_html"), historical=True)
        self._scroll_to_bottom()

    def finish_text_turn(self) -> None:
        """Settle a written reply while leaving its interactive output alive."""
        self.set_text_pending(False)
        self._finalize_current_bubble()
        self._end_reply()
        for row in self._tool_calls.values():
            if row.result is None:
                row.finish(ToolResult(row.call.id, "cancelled", "The request ended."))

    def end_session(self) -> None:
        """Keep displayed results, disconnect app actions and settle pending rows."""
        self.set_text_pending(False)
        self._finalize_current_bubble()
        self._end_reply()
        for bubble in self._bubbles():
            if not bubble.finalized:
                bubble.restore(bubble.snapshot())
            bubble.set_speaker_clickable(False)
            bubble.voice = ""
        self._voice_names.clear()
        for row in self._tool_calls.values():
            row.freeze_app()
            if row.result is None:
                row.finish(ToolResult(row.call.id, "cancelled", "The session ended."))

    def attach_app(
        self, call_id: str, html_content: str | None, *, historical: bool = False
    ) -> MCPAppWidget | None:
        """Attach interactive output to its existing row, preserving its position."""
        from roomkit_ui.widgets.mcp_app_widget import MCPAppWidget, has_webengine

        row = self.tool_call(call_id)
        if row is None or not html_content:
            return None
        row.app_html = html_content
        if not has_webengine():
            return None
        # The web view renders through a QQuickWidget, which Qt does not
        # support under a graphics effect: a result back within the row's
        # entrance fade (220 ms; MCP tools answer in about 50) would put it
        # under one.  The row appears at once instead.
        row.setGraphicsEffect(None)  # type: ignore[arg-type]
        widget = MCPAppWidget(row.call.name, row.call.server_name, parent=row)
        if historical:
            # Restoring a page can run its startup JS. No old tool may be
            # invoked again just because its conversation was opened.
            widget.set_read_only(row.app_results)
            try:
                arguments = json.loads(row.call.arguments_json)
            except (ValueError, TypeError):
                arguments = {}
            widget.send_tool_input(arguments if isinstance(arguments, dict) else {})
            if row.result is not None:
                widget.send_tool_result(row.result.text)
        widget.load_html(html_content)
        row.attach_app(widget)
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

    def _clear_rows(self) -> None:
        self.set_text_pending(False)
        self._empty_state.hide()
        self._live_empty.hide()
        self._scroll_timer.stop()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget and widget not in (self._empty_state, self._live_empty):
                if isinstance(widget, ChatBubble) and not widget.finalized:
                    widget.finalize(interrupted=True)
                widget.deleteLater()
        self._current_bubble = None
        self._reply = None
        self._end_reply()
        self._last_assistant_bubble = None
        self._tool_calls.clear()
        self._voice_names.clear()
        self._autoscroll = True

    def clear(self) -> None:
        """Start a fresh Live transcript with a centered invitation."""
        self._clear_rows()
        self._layout.addStretch()
        self._layout.addWidget(self._live_empty)
        self._layout.addStretch()
        self._live_empty.show()

    def reset(self) -> None:
        """Clear the session and return to the welcome page."""
        self._clear_rows()
        self._layout.addStretch()
        self._layout.addWidget(self._empty_state)
        self._layout.addStretch()
        self._empty_state.show()

    def _hide_live_prompt(self) -> None:
        if self._live_empty.isHidden() and self._empty_state.isHidden():
            return
        for prompt in (self._live_empty, self._empty_state):
            prompt.hide()
            self._layout.removeWidget(prompt)
        # Remove its leading stretch, keeping the one after the transcript.
        first = self._layout.itemAt(0)
        if first is not None and first.spacerItem() is not None:
            self._layout.takeAt(0)

    # -- internal ------------------------------------------------------------

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
