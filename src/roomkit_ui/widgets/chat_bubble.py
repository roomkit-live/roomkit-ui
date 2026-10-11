"""One chat entry — a subtle bubble for the user, typeset text for the AI."""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from roomkit_ui.theme import CHAT_FONT_SIZE_PX, colors, fixed_font_family
from roomkit_ui.theme_live import bind_theme, themed_style


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
    mono = f"font-family:'{fixed_font_family()}'"

    # Inject inline styles — QLabel ignores <style> blocks.
    replacements = {
        "<pre>": f'<pre style="background:{code_bg}; padding:8px 10px;'
        f' {mono}; font-size:12px; white-space:pre-wrap;">',
        "<code>": f'<code style="background:{code_bg}; {mono}; font-size:12px; padding:1px 4px;">',
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
        rf'\1<code style="{mono}; font-size:12px;">',
        body,
    )

    text_color = c["BUBBLE_AI_TEXT"]
    # Match the live-reveal typography (the label's own family, the shared
    # size) so finalization doesn't visibly reflow the text.
    return f'<div style="color:{text_color}; font-size:{CHAT_FONT_SIZE_PX}px;">{body}</div>'


# Assistant word-reveal pacing.  ~230 ms/word ≈ 260 WPM — deliberately a
# bit faster than speech (~150 WPM) so the text never lags far behind the
# voice, while still *rolling out* rather than appearing at once.  When the
# unrevealed backlog grows (a provider that delivers the transcript in big
# chunks, e.g. Grok), the reveal accelerates to catch up.
_STREAM_WORD_MS = 230
_STREAM_CATCHUP_MS = 80
_STREAM_BACKLOG_WORDS = 12

# How fast a voice goes through text, to tell what a cut reply had said
# when it was cut: ~16 characters a second (ElevenLabs in French, measured
# on whole replies).  roomkit reports how long the reply played, not the
# words: an estimate is all there is, and a word or two off is fine here.
_SPOKEN_MS_PER_CHAR = 60


def _said_in(text: str, heard_ms: int) -> str:
    """The words of *text* a voice had said after *heard_ms*, ending on a
    whole word, with "…" when the text goes on.  The first word at least:
    it showed at once, and an entry of "…" alone says nothing."""
    heard_chars = heard_ms // _SPOKEN_MS_PER_CHAR
    if heard_chars >= len(text):
        return text
    words: list[str] = []
    end = 0
    for word in text.split():
        end = text.index(word, end) + len(word)
        if end > heard_chars and words:
            break
        words.append(word)
    return _trail_off(" ".join(words))


def _trail_off(said: str) -> str:
    said = said.rstrip(",;:—–- ")
    return said if said.endswith((".", "!", "?", "…")) else said + "…"


class _SpeakerLabel(QLabel):
    """The speaker's name above a bubble; a plain click on it once it is nameable."""

    clicked = Signal()

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._clickable = False

    def set_clickable(self, clickable: bool) -> None:
        self._clickable = clickable
        self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        self.setToolTip("Click to say who this is" if clickable else "")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — Qt override
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ChatBubble(QFrame):
    """One chat entry: user/other in a right-hugging grey bubble with a
    timestamp; assistant as a bubble-less, full-column serif paragraph."""

    streaming_tick = Signal()
    speaker_clicked = Signal()

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
        # The voice the turn came from, when the STT tells voices apart
        # ("Speaker B"): the chat relabels it once it has a name.
        self.voice = ""
        self._finalized = False
        self.setToolTip(datetime.now().strftime("%H:%M"))
        self._raw_text = text

        # Word-by-word streaming state
        self._stream_words: list[str] = []
        self._stream_index = 0
        # When the first words showed: the voice started about then.
        self._stream_started: float | None = None
        self._stream_timer = QTimer(self)
        self._stream_timer.timeout.connect(self._stream_tick)
        self._streaming_connected = False
        # finalize() arrived while words were still revealing — complete
        # the animation first, then do the real finalization.
        self._finalize_pending = False

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
            bubble_color = "BUBBLE_OTHER_BG" if role == "other" else "BUBBLE_USER_BG"
            themed_style(
                self._bubble,
                lambda c: (
                    f"QFrame#bubbleFrame {{"
                    f"  background-color: {c[bubble_color]};"
                    f"  border-radius: 18px;"
                    f"  border-top-right-radius: 6px;"
                    f"}}"
                ),
            )
        else:
            self._bubble.setStyleSheet("QFrame#bubbleFrame { background: transparent; }")

        # ── Message text ──
        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.PlainText)
        # One conversation typeface for both speakers — the window's own
        # (theme.py), at a shared size; the roles differ only in *framing*
        # (the user's bubble vs the assistant's open column).
        if is_user:
            self._bubble.setMaximumWidth(304)
            themed_style(
                self._label,
                lambda c: (
                    f"QLabel {{"
                    f"  color: {(c['BUBBLE_USER_TEXT'] if is_user else c['BUBBLE_AI_TEXT'])};"
                    f"  font-size: {CHAT_FONT_SIZE_PX}px;"
                    f"  line-height: 1.5;"
                    f"  padding: 11px 14px 11px 14px;"
                    f"  background: transparent;"
                    f"}}"
                ),
            )
        else:
            # No width cap on the label itself: it fills the (capped)
            # container, so the wrap measure is fixed by layout, not by
            # content — that is what keeps the word reveal steady.
            themed_style(
                self._label,
                lambda c: (
                    f"QLabel {{"
                    f"  color: {(c['BUBBLE_USER_TEXT'] if is_user else c['BUBBLE_AI_TEXT'])};"
                    f"  font-size: {CHAT_FONT_SIZE_PX}px;"
                    f"  line-height: 1.55;"
                    f"  padding: 6px 14px 6px 14px;"
                    f"  background: transparent;"
                    f"}}"
                ),
            )

        bubble_layout = QVBoxLayout(self._bubble)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(0)
        bubble_layout.addWidget(self._label)
        if not is_user:
            # Cap the measure on the container; the trailing row stretch
            # below pins it left when the window is wider than the measure.
            self._bubble.setMaximumWidth(680)

        # ── Row: user bubble hugs the right; assistant text owns the row ──
        # Giving the assistant container the full row width (stretch 1, no
        # trailing spacer) is what keeps the word reveal steady: the text
        # wraps inside a fixed measure instead of resizing its own box.
        row = QHBoxLayout()
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(0)
        if is_user:
            row.addStretch()
            row.addWidget(self._bubble)
        else:
            row.addWidget(self._bubble, 1)
            row.addStretch()

        # ── Barge-in marker ── (assistant only; shown when cut short)
        self._interrupted_label: QLabel | None = None
        if not is_user:
            self._interrupted_label = QLabel("— interrupted")
            themed_style(
                self._interrupted_label,
                lambda c: (
                    f"QLabel {{"
                    f"  color: {c['TEXT_SECONDARY']};"
                    f"  font-size: 11px;"
                    f"  background: transparent;"
                    f"  padding: 0px 14px 2px 14px;"
                    f"}}"
                ),
            )
            self._interrupted_label.setVisible(False)

        # ── Outer layout ──
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 1)
        outer.setSpacing(0)

        # ── Speaker name label (shown above bubble for identified speakers) ──
        self._speaker_label: _SpeakerLabel | None = None
        if is_user:
            self._speaker_label = _SpeakerLabel(speaker_name or "")
            self._speaker_label.clicked.connect(self.speaker_clicked)
            spk_align = Qt.AlignRight if role == "user" else Qt.AlignLeft
            self._speaker_label.setAlignment(spk_align)
            themed_style(
                self._speaker_label,
                lambda c: (
                    f"QLabel {{"
                    f"  color: {c['SPEAKER_LABEL']};"
                    f"  font-size: 10px;"
                    f"  font-weight: 500;"
                    f"  background: transparent;"
                    f"  padding: 0px 14px 1px 14px;"
                    f"}}"
                ),
            )
            self._speaker_label.setVisible(bool(speaker_name))
            outer.addWidget(self._speaker_label)

        outer.addLayout(row)
        if self._interrupted_label is not None:
            outer.addWidget(self._interrupted_label)
        self.setStyleSheet("background: transparent;")
        bind_theme(self, self._refresh_markdown)

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

    def set_speaker_clickable(self, clickable: bool) -> None:
        if self._speaker_label is not None:
            self._speaker_label.set_clickable(clickable)

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
        self._stream_started = time.monotonic()
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

    def finalize(self, *, interrupted: bool = False) -> None:
        """Freeze the bubble — after the reveal finishes, if one is running.

        A provider that sends its full transcript before the audio ends
        (Grok, OpenAI) finalizes almost immediately; snapping the complete
        text into place here is what killed the rolling-text feel.  The
        animation is left to finish and the real finalization (markdown
        render, timestamp) happens on its last tick.

        *interrupted* is the exception: the voice already stopped, so a
        reveal still pacing itself would be theater — the text lands at
        once, marked as cut short (cut_short() first trims it to what was
        said).
        """
        if interrupted:
            if self._interrupted_label is not None:
                self._interrupted_label.setVisible(True)
            self._complete_finalize()
            return
        if self._role not in ("user", "other") and self._stream_index < len(self._stream_words):
            self._finalize_pending = True
            if not self._stream_timer.isActive():
                self._stream_timer.start()
            return
        self._complete_finalize()

    def cut_short(self, heard_ms: int = -1) -> None:
        """The voice was cut: keep only what it had said, marked as cut short.

        *heard_ms* is how much of the reply played.  At -1 (not measured)
        the time since its first words showed stands for it: the words
        revealed do not, since a reveal catching up on a provider's text
        (Gemini writes ahead of its voice) runs past the voice.
        """
        if heard_ms < 0 and self._stream_started is not None:
            heard_ms = int((time.monotonic() - self._stream_started) * 1000)
        if heard_ms >= 0:
            self._raw_text = _said_in(self._raw_text, heard_ms)
        self.finalize(interrupted=True)

    def _refresh_markdown(self) -> None:
        if self._finalized and self._role not in ("user", "other"):
            self._label.setText(_markdown_to_html(self._raw_text, colors()))

    def _complete_finalize(self) -> None:
        self._finalize_pending = False
        self._stream_timer.stop()
        if self._streaming_connected:
            self._stream_timer.timeout.disconnect(self.streaming_tick.emit)
            self._streaming_connected = False
        self._finalized = True
        # Update timestamp to finalization time
        self.setToolTip(datetime.now().strftime("%H:%M"))

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
