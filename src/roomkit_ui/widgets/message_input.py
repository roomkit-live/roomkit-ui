"""A draft editor that grows to eight visual lines, then scrolls."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QMimeData, Qt, Signal
from PySide6.QtWidgets import QFrame, QPlainTextEdit


class MessageInput(QPlainTextEdit):
    send_requested = Signal()
    images_inserted = Signal(object)
    MAX_LINES = 8

    def __init__(self) -> None:
        super().__init__()
        self._sizing = False
        self.setFrameShape(QFrame.NoFrame)
        self.setTabChangesFocus(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.document().setDocumentMargin(4)
        self.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none; font-size: 15px; }"
        )
        self.document().documentLayout().documentSizeChanged.connect(self._fit_draft)
        self.textChanged.connect(self._fit_draft)
        self._fit_draft()

    def _fit_draft(self) -> None:
        if self._sizing:
            return
        self._sizing = True
        try:
            lines = min(self.MAX_LINES, max(1, self.document().lineCount()))
            # Qt includes a cursor/bottom-edge allowance in its scroll range.
            padding = 2 * (self.document().documentMargin() + self.frameWidth()) + 2
            height = max(30, math.ceil(lines * self.fontMetrics().lineSpacing() + padding))
            if height != self.height():
                self.setFixedHeight(height)
        finally:
            self._sizing = False

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_draft()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange) and hasattr(self, "_sizing"):
            self._fit_draft()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            if self.isEnabled() and not self.isReadOnly():
                self.send_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _has_images(source: QMimeData) -> bool:
        return source.hasImage() or any(url.isLocalFile() for url in source.urls())

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        return self._has_images(source) or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if not self.isEnabled() or self.isReadOnly():
            return
        if self._has_images(source):
            self.images_inserted.emit(source)
        else:
            super().insertFromMimeData(source)
