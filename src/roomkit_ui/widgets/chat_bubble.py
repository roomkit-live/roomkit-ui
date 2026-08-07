"""One chat entry — a subtle bubble for the user, typeset text for the AI."""

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
    # Match the live-reveal typography (15px; the serif comes from the
    # QLabel stylesheet) so finalization doesn't visibly reflow the text.
    return f'<div style="color:{text_color}; font-size:15px;">{body}</div>'


# Assistant word-reveal pacing.  ~230 ms/word ≈ 260 WPM — deliberately a
# bit faster than speech (~150 WPM) so the text never lags far behind the
# voice, while still *rolling out* rather than appearing at once.  When the
# unrevealed backlog grows (a provider that delivers the transcript in big
# chunks, e.g. Grok), the reveal accelerates to catch up.
_STREAM_WORD_MS = 230
_STREAM_CATCHUP_MS = 80
_STREAM_BACKLOG_WORDS = 12


class ChatBubble(QFrame):
    """One chat entry: user/other in a right-hugging grey bubble with a
    timestamp; assistant as a bubble-less, full-column serif paragraph."""

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
        self._streaming_connected = False
        # finalize() arrived while words were still revealing — complete
        # the animation first, then do the real finalization.
        self._finalize_pending = False

        c = colors()
        is_user = role in ("user", "other")

        # ── Container ──
        # User/other messages keep a subtle bubble; assistant text renders
        # bubble-less, as a full-column typeset paragraph (the modern
        # AI-chat look).  A fixed-width paragraph also keeps the word
        # reveal calm: only the height grows, line by line — the old
        # width-hugging bubble reflowed in both axes on every tick.
        self._bubble = QFrame()
        self._bubble.setObjectName("bubbleFrame")
        if is_user:
            bg = c["BUBBLE_OTHER_BG"] if role == "other" else c["BUBBLE_USER_BG"]
            self._bubble.setStyleSheet(
                f"QFrame#bubbleFrame {{"
                f"  background-color: {bg};"
                f"  border-radius: 18px;"
                f"  border-top-right-radius: 4px;"
                f"}}"
            )
        else:
            self._bubble.setStyleSheet("QFrame#bubbleFrame { background: transparent; }")

        # ── Message text ──
        text_color = c["BUBBLE_USER_TEXT"] if is_user else c["BUBBLE_AI_TEXT"]
        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.PlainText)
        if is_user:
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
        else:
            # Readable measure, generous leading, a serif for the voice of
            # the assistant — text, not a speech balloon.  No width cap on
            # the label itself: it fills the (capped) container, so the
            # wrap measure is fixed by layout, not by content.
            self._label.setStyleSheet(
                f"QLabel {{"
                f"  color: {text_color};"
                f"  font-family: 'Iowan Old Style', 'Palatino', Georgia, serif;"
                f"  font-size: 15px;"
                f"  line-height: 1.55;"
                f"  padding: 6px 14px 6px 14px;"
                f"  background: transparent;"
                f"}}"
            )

        bubble_layout = QVBoxLayout(self._bubble)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(0)
        bubble_layout.addWidget(self._label)
        if not is_user:
            # Cap the measure on the container; the trailing row stretch
            # below pins it left when the window is wider than the measure.
            self._bubble.setMaximumWidth(680)

        # ── Timestamp ── (user messages only; assistant text stays clean)
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
        if not is_user:
            self._time_label.setVisible(False)

        # ── Row: user bubble hugs the right; assistant text owns the row ──
        # Giving the assistant container the full row width (stretch 1, no
        # trailing spacer) is what keeps the word reveal steady: the text
        # wraps inside a fixed measure instead of resizing its own box.
        row = QHBoxLayout()
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(0)
        if is_user:
            row.addStretch()
            row.addWidget(self._bubble)
        else:
            row.addWidget(self._bubble, 1)
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
        """Begin the word-by-word reveal for an assistant bubble.

        The reveal is paced (see the module constants) so the text *rolls
        out* roughly alongside the voice instead of appearing at once, and
        ``update_stream`` extends the target text without resetting the
        words already shown.
        """
        self._stream_timer.stop()
        if not self._streaming_connected:
            self._stream_timer.timeout.connect(self.streaming_tick.emit)
            self._streaming_connected = True
        self._stream_words = []
        self._stream_index = 0
        self.update_stream(full_text)

    def update_stream(self, full_text: str) -> None:
        """Update the reveal target with a newer (fuller) transcript.

        Providers deliver the transcript on their own cadence — Gemini in a
        trickle, Grok in a few large chunks — so the target text may jump
        while the reveal keeps its own pace; a growing backlog accelerates
        the timer instead of snapping the text into place.
        """
        self._raw_text = full_text
        self._stream_words = full_text.split()
        if not self._stream_words:
            self._label.setText(full_text)
            return
        if self._stream_index == 0:
            # First words show immediately — the bubble must not sit empty.
            self._stream_index = 1
            self._label.setText(self._stream_words[0])
        if self._stream_index < len(self._stream_words) and not self._stream_timer.isActive():
            self._stream_timer.setInterval(_STREAM_WORD_MS)
            self._stream_timer.start()

    def _stream_tick(self) -> None:
        """Reveal the next word; complete a pending finalization at the end."""
        if self._stream_index >= len(self._stream_words):
            self._stream_timer.stop()
            if self._finalize_pending:
                self._complete_finalize()
            return
        self._stream_index += 1
        self._label.setText(" ".join(self._stream_words[: self._stream_index]))
        backlog = len(self._stream_words) - self._stream_index
        self._stream_timer.setInterval(
            _STREAM_CATCHUP_MS if backlog > _STREAM_BACKLOG_WORDS else _STREAM_WORD_MS
        )

    def finalize(self) -> None:
        """Freeze the bubble — after the reveal finishes, if one is running.

        A provider that sends its full transcript before the audio ends
        (Grok, OpenAI) finalizes almost immediately; snapping the complete
        text into place here is what killed the rolling-text feel.  The
        animation is left to finish and the real finalization (markdown
        render, timestamp) happens on its last tick.
        """
        if self._role not in ("user", "other") and self._stream_index < len(self._stream_words):
            self._finalize_pending = True
            if not self._stream_timer.isActive():
                self._stream_timer.start()
            return
        self._complete_finalize()

    def _complete_finalize(self) -> None:
        self._finalize_pending = False
        self._stream_timer.stop()
        if self._streaming_connected:
            self._stream_timer.timeout.disconnect(self.streaming_tick.emit)
            self._streaming_connected = False
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
