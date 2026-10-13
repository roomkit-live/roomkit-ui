"""Growing text composer and Live controls on the same surface."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPalette, QTextCursor, QTextLayout
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.engine_state import EngineState
from roomkit_ui.icons import svg_icon
from roomkit_ui.images import ImageAttachment
from roomkit_ui.stt_engine import DictationState
from roomkit_ui.text_chat import CONFIGURATION_HINT
from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.widgets.buttons import KeyboardButton
from roomkit_ui.widgets.image_attachments import ImageAttachments
from roomkit_ui.widgets.message_input import MessageInput


class ConversationComposer(QWidget):
    """Send typed turns when configured, or open Live with an empty draft."""

    start_requested = Signal()
    send_requested = Signal(str)
    stop_requested = Signal()
    mute_toggled = Signal(bool)
    dictation_requested = Signal()
    dictation_cancelled = Signal()
    draft_cleared = Signal()
    images_shared = Signal(object)  # tuple[ImageAttachment, ...] shared while Live

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("ConversationComposer { background: transparent; }")
        self.setAcceptDrops(True)
        self._state: str = EngineState.IDLE
        self._text_mode = False
        self._expanded = False
        self._voice_controls = False
        self._images_unavailable = ""
        self._live_images_unavailable = ""
        self._dictation_unavailable = "Configure speech recognition in Settings → Dictation."
        self._dictation_state = DictationState.IDLE
        self._external_dictation = False
        self._dictation_error = ""
        self._dictation_cursor: QTextCursor | None = None
        self._unavailable = "Configure a chat model in Settings…"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 18)
        layout.setSpacing(12)
        self._dictation_feedback = QWidget()
        self._dictation_feedback.setStyleSheet("QWidget { background: transparent; }")
        feedback = QHBoxLayout(self._dictation_feedback)
        feedback.setContentsMargins(12, 0, 8, 0)
        self._dictation_label = QLabel()
        self._dictation_label.setWordWrap(True)
        self._dictation_label.setTextFormat(Qt.PlainText)
        feedback.addWidget(self._dictation_label, 1)
        self._cancel_dictation = self._icon_button("Cancel dictation")
        self._cancel_dictation.clicked.connect(self._dismiss_dictation)
        feedback.addWidget(self._cancel_dictation)
        layout.addWidget(self._dictation_feedback)
        self._surface = QFrame()
        self._surface.setObjectName("conversationComposer")
        layout.addWidget(self._surface)
        self._stack = QVBoxLayout(self._surface)
        self._stack.setContentsMargins(8, 8, 8, 8)
        self._stack.setSpacing(6)
        self._attachments = ImageAttachments()
        self._stack.addWidget(self._attachments)
        inner = QHBoxLayout()
        self._inner = inner
        self._stack.addLayout(inner)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(6)
        inner.addStretch(0)

        self._attachment_button = self._icon_button("Add images")
        self._attachment_button.clicked.connect(
            lambda: self._attachments.menu(self._attachment_button)
        )
        inner.addWidget(self._attachment_button, 0, Qt.AlignBottom)

        self._input = MessageInput()
        self._input.setAccessibleName("Message RoomKit")
        self._input.textChanged.connect(self._refresh)
        self._input.send_requested.connect(self._send)
        self._input.images_inserted.connect(self._attachments.add_mime)
        inner.addWidget(self._input, 1)

        self._dictation_button = self._icon_button("Dictate a message")
        self._dictation_button.clicked.connect(self.dictation_requested.emit)
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
        self._attachments.changed.connect(self._on_attachments_changed)
        bind_theme(self, self._refresh)

    @staticmethod
    def _icon_button(name: str) -> KeyboardButton:
        button = KeyboardButton()
        button.setFixedSize(36, 44)
        button.setIconSize(QSize(20, 20))
        button.setAccessibleName(name)
        button.setToolTip(name)
        button.setFocusPolicy(Qt.StrongFocus)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")
        return button

    def set_text_availability(self, reason: str) -> None:
        self._unavailable = reason
        self._refresh()

    @property
    def images(self) -> tuple[ImageAttachment, ...]:
        return self._attachments.images

    def set_live_image_availability(self, reason: str) -> None:
        """Why the live session cannot take a shared image, "" when it can."""
        self._live_images_unavailable = reason
        self._refresh()

    def _on_attachments_changed(self) -> None:
        # While Live an image is not a draft: it goes to the session at once.
        live = not self._text_mode and self._state == EngineState.ACTIVE
        if live and self._attachments.images:
            images = self._attachments.images
            self._attachments.clear()  # emits changed again, with nothing to share
            self.images_shared.emit(images)
            return
        self._refresh()

    def set_image_availability(self, reason: str) -> None:
        self._images_unavailable = reason
        self._refresh()

    def clear_draft(self) -> None:
        self.draft_cleared.emit()
        self._dictation_cursor = None
        self._dictation_error = ""
        self._attachments.clear()
        self._input.clear()

    def set_dictation_availability(self, reason: str) -> None:
        self._dictation_unavailable = reason
        self._refresh()

    def set_dictation_state(self, state: DictationState, *, external: bool = False) -> None:
        if state is DictationState.STARTING and not external:
            self._dictation_error = ""
            self._dictation_cursor = QTextCursor(self._input.textCursor())
        self._dictation_state = state if not external else DictationState.IDLE
        self._external_dictation = external and state is not DictationState.IDLE
        self._refresh()

    def show_dictation_error(self, message: str) -> None:
        self._dictation_error = message
        self._refresh()

    def insert_dictation(self, text: str) -> None:
        cursor = self._dictation_cursor
        if cursor is None or not text.strip():
            return
        # QTextCursor positions count UTF-16 units, unlike Python string indices.
        document = self._input.document()
        before = document.characterAt(cursor.selectionStart() - 1)
        after = document.characterAt(cursor.selectionEnd())
        text = text.strip()
        if cursor.selectionStart() > 0 and not before.isspace():
            text = " " + text
        if (
            cursor.selectionEnd() < document.characterCount() - 1
            and not after.isspace()
            and after not in ".,!?;:)]}"
        ):
            text += " "
        cursor.beginEditBlock()
        cursor.insertText(text)
        cursor.endEditBlock()
        self._input.setTextCursor(cursor)
        self._dictation_cursor = None

    def _dismiss_dictation(self) -> None:
        self._dictation_cursor = None
        self._dictation_error = ""
        self.dictation_cancelled.emit()
        self._refresh()

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
        expanded = bool(self.images) and not self._voice_controls
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
                expanded |= measure.createLine().isValid()
                measure.endLayout()
        if expanded == self._expanded:
            return
        self._expanded = expanded
        if expanded:
            self._inner.removeWidget(self._input)
            self._inner.insertStretch(2, 1)
            self._stack.insertWidget(1, self._input)
        else:
            self._stack.removeWidget(self._input)
            self._inner.takeAt(2)  # The spacer used by the expanded action row.
            self._inner.insertWidget(2, self._input, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._arrange_input()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if (
            not self._voice_controls
            and not self._unavailable
            and MessageInput._has_images(event.mimeData())
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not self._voice_controls and not self._unavailable:
            self._attachments.add_mime(event.mimeData())
            event.acceptProposedAction()
        else:
            event.ignore()

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
        dictating = self._dictation_state is not DictationState.IDLE
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
        elif (
            not busy
            and not self._unavailable
            and (self._input.toPlainText().strip() or self.images)
        ):
            name, glyph = "Send message", "arrow-up"
        self._live_button.setAccessibleName(name)
        self._live_button.setToolTip(name)
        self._live_button.setEnabled(
            not stopping and not dictating and not self._external_dictation
        )
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
        self._input.setReadOnly(not ready or dictating)
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
        # While Live, the + shares an image with the session, beside the mic.
        self._attachment_button.setVisible(not busy or live)
        image_reason = self._unavailable or self._images_unavailable
        if live:
            image_reason = self._live_images_unavailable
        elif busy:
            image_reason = "Wait for the live conversation to start."
        self._attachments.set_availability(image_reason)
        notice = bool(self._attachments._notice.text())
        self._attachments.setVisible(
            (not busy and (bool(self.images) or notice)) or (live and notice)
        )
        self._attachment_button.setEnabled(not image_reason)
        action = "Share an image" if live else "Add images"
        self._attachment_button.setAccessibleName(action)
        self._attachment_button.setToolTip(image_reason or f"{action} from a file or camera")
        if self.images and self._images_unavailable and not busy:
            self._attachments.notice(self._images_unavailable)
        self._dictation_button.setVisible(not busy)
        if live:
            self._attachment_button.setFixedSize(56, 56)
            self._attachment_button.setIconSize(QSize(24, 24))
            self._attachment_button.setIcon(svg_icon("photo", c["TEXT_PRIMARY"], 24))
            self._attachment_button.setStyleSheet(
                f"QPushButton {{ background: {c['BG_SECONDARY']};"
                f" border: 1px solid {c['BG_TERTIARY']};"
                " border-radius: 28px; padding: 0; }"
                f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
                f"QPushButton:disabled {{ background: {c['BG_SECONDARY']}; }}"
                'QPushButton[keyboardFocus="true"] {'
                f" border-color: {c['ACCENT_BRAND']}; }}"
            )
        else:
            self._attachment_button.setFixedSize(36, 44)
            self._attachment_button.setIconSize(QSize(20, 20))
            self._attachment_button.setIcon(svg_icon("plus", c["TEXT_SECONDARY"], 20))
            self._attachment_button.setStyleSheet(
                "QPushButton { background: transparent; border: none; padding: 0; }"
            )
        self._refresh_dictation(c, busy or text_busy or not ready)
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
        if self._dictation_state is not DictationState.IDLE or self._external_dictation:
            return
        if self._state in (EngineState.ACTIVE, EngineState.CONNECTING):
            self.stop_requested.emit()
            if self._text_mode:
                self.focus_input()
        elif self._state in (EngineState.IDLE, EngineState.ERROR, EngineState.READY):
            if not self._unavailable and (self._input.toPlainText().strip() or self.images):
                self._send()
            else:
                self.start_requested.emit()

    def _send(self) -> None:
        if self._dictation_state is not DictationState.IDLE or self._external_dictation:
            return
        if self._unavailable or self._state not in (
            EngineState.IDLE,
            EngineState.ERROR,
            EngineState.READY,
        ):
            return
        if self.images and self._images_unavailable:
            self._attachments.notice(self._images_unavailable)
            return
        text = self._input.toPlainText().strip()
        if text or self.images:
            self.send_requested.emit(text)

    def _on_mute(self, muted: bool) -> None:
        self._refresh()
        self.mute_toggled.emit(muted)

    def _refresh_dictation(self, c: dict, blocked: bool) -> None:
        state = self._dictation_state
        active = state is not DictationState.IDLE
        recording = state is DictationState.RECORDING
        label = {
            DictationState.STARTING: "Preparing microphone…",
            DictationState.RECORDING: "Listening…",
            DictationState.STOPPING: "Transcribing…",
        }.get(state, self._dictation_error)
        self._dictation_feedback.setVisible(bool(label))
        self._dictation_label.setText(label)
        self._dictation_label.setStyleSheet(
            f"color: {c['ACCENT_BRAND'] if active else c['TEXT_SECONDARY']}; font-size: 13px;"
        )
        self._cancel_dictation.setIcon(svg_icon("x-mark", c["TEXT_SECONDARY"], 18))
        cancel_name = "Cancel dictation" if active else "Dismiss dictation message"
        self._cancel_dictation.setAccessibleName(cancel_name)
        self._cancel_dictation.setToolTip(cancel_name)
        name = "Finish dictation" if recording else "Dictate a message"
        self._dictation_button.setAccessibleName(name)
        self._dictation_button.setToolTip(
            label if active else self._unavailable or self._dictation_unavailable or name
        )
        self._dictation_button.setEnabled(
            recording
            or (
                not active
                and not blocked
                and not self._dictation_unavailable
                and not self._external_dictation
            )
        )
        self._dictation_button.setIcon(
            svg_icon(
                "stop" if active else "microphone",
                c["ACCENT_BRAND"] if active else c["TEXT_SECONDARY"],
                20,
            )
        )
        self._dictation_button.setStyleSheet(
            "QPushButton { border: 1px solid transparent; border-radius: 18px; padding: 0;"
            f" background: {c['BG_TERTIARY'] if active else 'transparent'}; }}"
            f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
            'QPushButton[keyboardFocus="true"] {'
            f" border-color: {c['ACCENT_BRAND']}; }}"
        )
