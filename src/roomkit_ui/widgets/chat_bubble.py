"""Single iMessage-style chat bubble with timestamp."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from roomkit_ui.theme import colors


def _markdown_to_html(text: str, c: dict[str, str]) -> str:
    """Convert markdown *text* to inline-styled HTML suitable for QLabel.

    QLabel only supports a subset of HTML (no <style> blocks), so we inject
    inline ``style=`` attributes via simple string replacements.
    """
    import re

    from markdown_it import MarkdownIt

    md = MarkdownIt().enable("table")
    body = md.render(text)

    code_bg = c["CODE_BG"]
    accent = c["ACCENT_BLUE"]

    # Inject inline styles — QLabel ignores <style> blocks.
    replacements = {
        "<pre>": f'<pre style="background:{code_bg}; padding:8px 10px;'
        f' font-family:monospace; font-size:12px; white-space:pre-wrap;">',
        "<code>": f'<code style="background:{code_bg}; font-family:monospace;'
        f' font-size:12px; padding:1px 4px;">',
        "<table>": '<table style="border-collapse:collapse; margin:4px 0;" cellpadding="4">',
        "<th>": '<th style="border-bottom:1px solid; padding:4px 8px; text-align:left;">',
        "<td>": '<td style="padding:4px 8px;">',
        "<a ": f'<a style="color:{accent};" ',
    }
    for old, new in replacements.items():
        body = body.replace(old, new)

    # Strip background from <code> inside <pre> (already has bg)
    body = re.sub(
        r"(<pre[^>]*>)\s*<code[^>]*>",
        r'\1<code style="font-family:monospace; font-size:12px;">',
        body,
    )

    text_color = c["BUBBLE_AI_TEXT"]
    return f'<div style="color:{text_color}; font-size:13px;">{body}</div>'


class ChatBubble(QFrame):
    """A rounded chat bubble — blue/right for user, gray/left for AI."""

    streaming_tick = Signal()

    def __init__(
        self,
        text: str,
        role: str = "assistant",
        parent=None,
        speaker_name: str = "",
    ) -> None:
        super().__init__(parent)
        self._role = role
        self._speaker_name = speaker_name
        self._finalized = False
        self._created = datetime.now()
        self._raw_text = text

        # Word-by-word streaming state
        self._stream_words: list[str] = []
        self._stream_index = 0
        self._stream_timer = QTimer(self)
        self._stream_timer.timeout.connect(self._stream_tick)

        c = colors()
        is_user = role in ("user", "other")

        # ── Bubble container ──
        self._bubble = QFrame()
        self._bubble.setObjectName("bubbleFrame")
        if role == "other":
            bg = c["BUBBLE_OTHER_BG"]
        elif role == "user":
            bg = c["BUBBLE_USER_BG"]
        else:
            bg = c["BUBBLE_AI_BG"]
        self._bubble.setStyleSheet(
            f"QFrame#bubbleFrame {{"
            f"  background-color: {bg};"
            f"  border-radius: 18px;"
            f"  border-top-{'right' if is_user else 'left'}-radius: 4px;"
            f"}}"
        )

        # ── Message text ──
        text_color = c["BUBBLE_USER_TEXT"] if is_user else c["BUBBLE_AI_TEXT"]
        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.PlainText)
        self._label.setMaximumWidth(380)
        self._label.setStyleSheet(
            f"QLabel {{"
            f"  color: {text_color};"
            f"  font-size: 13px;"
            f"  line-height: 1.4;"
            f"  padding: 10px 14px 8px 14px;"
            f"  background: transparent;"
            f"}}"
        )

        bubble_layout = QVBoxLayout(self._bubble)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(0)
        bubble_layout.addWidget(self._label)

        # ── Timestamp ──
        self._time_label = QLabel(self._created.strftime("%H:%M"))
        align = Qt.AlignRight if is_user else Qt.AlignLeft
        self._time_label.setAlignment(align)
        self._time_label.setStyleSheet(
            f"QLabel {{"
            f"  color: {c['TEXT_SECONDARY']};"
            f"  font-size: 10px;"
            f"  background: transparent;"
            f"  padding: 2px 4px 0px 4px;"
            f"}}"
        )

        # ── Row: bubble aligned left or right ──
        row = QHBoxLayout()
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(0)
        if is_user:
            row.addStretch()
            row.addWidget(self._bubble)
        else:
            row.addWidget(self._bubble)
            row.addStretch()

        # ── Time row ──
        time_row = QHBoxLayout()
        time_row.setContentsMargins(14, 0, 14, 0)
        if is_user:
            time_row.addStretch()
            time_row.addWidget(self._time_label)
        else:
            time_row.addWidget(self._time_label)
            time_row.addStretch()

        # ── Outer layout ──
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 1)
        outer.setSpacing(0)

        # ── Speaker name label (shown above bubble for identified speakers) ──
        self._speaker_label: QLabel | None = None
        if is_user:
            self._speaker_label = QLabel(speaker_name or "")
            spk_align = Qt.AlignRight if role == "user" else Qt.AlignLeft
            self._speaker_label.setAlignment(spk_align)
            self._speaker_label.setStyleSheet(
                f"QLabel {{"
                f"  color: {c['SPEAKER_LABEL']};"
                f"  font-size: 10px;"
                f"  font-weight: 500;"
                f"  background: transparent;"
                f"  padding: 0px 14px 1px 14px;"
                f"}}"
            )
            self._speaker_label.setVisible(bool(speaker_name))
            outer.addWidget(self._speaker_label)

        outer.addLayout(row)
        outer.addLayout(time_row)
        self.setStyleSheet("background: transparent;")

    @property
    def role(self) -> str:
        return self._role

    @property
    def finalized(self) -> bool:
        return self._finalized

    def set_speaker_name(self, name: str) -> None:
        self._speaker_name = name
        if self._speaker_label is not None:
            self._speaker_label.setText(name)
            self._speaker_label.setVisible(bool(name))

    def set_text(self, text: str) -> None:
        self._raw_text = text
        self._label.setText(text)

    def append_text(self, text: str) -> None:
        self._raw_text += text
        self._label.setText(self._raw_text)

    def text(self) -> str:
        return self._raw_text

    def start_streaming(self, full_text: str) -> None:
        """Start word-by-word reveal animation for assistant bubbles.

        Words appear progressively, paced to roughly match TTS speaking
        speed (~150 WPM).  The timer is stopped when finalize() is called.
        """
        self._stream_timer.stop()
        self._stream_timer.timeout.connect(self.streaming_tick.emit)
        self._raw_text = full_text
        self._stream_words = full_text.split()
        self._stream_index = 0

        if not self._stream_words:
            self._label.setText(full_text)
            return

        # Pace: spread words across estimated speaking time.
        # ~150 WPM = 400ms/word, but cap interval to keep it snappy.
        n = len(self._stream_words)
        interval = max(40, min(120, int(n * 400 / n)))  # clamp 40-120ms
        # For short responses, reveal faster
        if n <= 5:
            interval = 40
        self._stream_timer.setInterval(interval)
        # Show first word immediately
        self._stream_index = 1
        self._label.setText(self._stream_words[0])
        if n > 1:
            self._stream_timer.start()

    def _stream_tick(self) -> None:
        """Reveal the next word(s)."""
        if self._stream_index >= len(self._stream_words):
            self._stream_timer.stop()
            return
        self._stream_index += 1
        visible = " ".join(self._stream_words[: self._stream_index])
        self._label.setText(visible)

    def finalize(self) -> None:
        self._stream_timer.stop()
        try:
            self._stream_timer.timeout.disconnect(self.streaming_tick.emit)
        except RuntimeError:
            pass  # not connected
        self._finalized = True
        # Update timestamp to finalization time
        self._time_label.setText(datetime.now().strftime("%H:%M"))

        # Render markdown for assistant bubbles only
        if self._role not in ("user", "other"):
            try:
                c = colors()
                html = _markdown_to_html(self._raw_text, c)
                self._label.setTextFormat(Qt.RichText)
                self._label.setText(html)
                self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            except Exception:
                pass  # keep plain text on failure
