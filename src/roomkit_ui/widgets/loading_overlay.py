"""Full-window loading overlay shown while a session connects.

Session startup used to narrate itself as raw status rows in the chat
("Reading CLI tools…", diarization notices) — functional, but it read as
debris.  The overlay covers the whole window with the app background, a
rotating arc spinner and the current step, then fades away when the
session goes active (the notices land in the chat underneath, readable
once the curtain lifts).
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors

_SPINNER_SIZE = 44
_SPINNER_ARC_SPAN = 300 * 16  # Qt angles are in 1/16 °
_SPINNER_STEP_DEG = 5
_FADE_OUT_MS = 260


class _Spinner(QWidget):
    """Indeterminate rotating arc — a thin ring with a moving gap."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_SPINNER_SIZE, _SPINNER_SIZE)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 fps
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._angle = (self._angle - _SPINNER_STEP_DEG) % 360
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(colors()["ACCENT_GREEN"]), 3.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        margin = 4.0
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)
        p.drawArc(rect, self._angle * 16, _SPINNER_ARC_SPAN)
        p.end()


class LoadingOverlay(QWidget):
    """Covers its parent while the session loads; fades out on dismiss."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        c = colors()
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"background-color: {c['BG_PRIMARY']};")

        self._spinner = _Spinner()
        self._status = QLabel("Starting…")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"color: {c['TEXT_SECONDARY']}; font-size: 13px; background: transparent;"
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(18)
        layout.addStretch()
        layout.addWidget(self._spinner, 0, Qt.AlignHCenter)
        layout.addWidget(self._status, 0, Qt.AlignHCenter)
        layout.addStretch()

        self._fade: QPropertyAnimation | None = None
        parent.installEventFilter(self)
        self.hide()

    # -- public API ----------------------------------------------------------

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def show_loading(self) -> None:
        """Cover the parent and start spinning (cancels a pending fade)."""
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        self.setGraphicsEffect(None)  # type: ignore[arg-type]
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._spinner.start()
        self.show()
        self.raise_()

    def dismiss(self) -> None:
        """Fade the curtain out, then stop the spinner and hide."""
        if self.isHidden() or self._fade is not None:
            return
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(_FADE_OUT_MS)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.InOutQuad)
        fade.finished.connect(self._on_fade_done)
        self._fade = fade
        fade.start()

    # -- internals -----------------------------------------------------------

    def _on_fade_done(self) -> None:
        self._fade = None
        self._spinner.stop()
        self.hide()
        self.setGraphicsEffect(None)  # type: ignore[arg-type]

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        # Track the parent's size so the curtain always covers the window.
        parent = self.parentWidget()
        if parent is not None and obj is parent and event.type() == QEvent.Resize:
            if not self.isHidden():
                self.setGeometry(parent.rect())
        return False
