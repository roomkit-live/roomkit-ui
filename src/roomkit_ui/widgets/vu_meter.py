"""Compact violet voice activity, driven by microphone and playback levels."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme


class VUMeter(QWidget):
    """One quiet waveform; muting suppresses mic activity, never playback."""

    DECAY = 0.88

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(68)
        self.setMinimumWidth(100)
        self.setStyleSheet("background: transparent;")
        self.setAccessibleName("Voice activity")
        self._mic_level = self._mic_display = 0.0
        self._spk_level = self._spk_display = 0.0
        self._phase = 0.0
        self._muted = False
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        bind_theme(self, self.update)

    def set_mic_level(self, level: float) -> None:
        self._mic_level = 0.0 if self._muted else max(0.0, min(1.0, level))

    def set_speaker_level(self, level: float) -> None:
        self._spk_level = max(0.0, min(1.0, level))

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        if muted:
            self._mic_level = self._mic_display = 0.0
        self.update()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._mic_level = self._mic_display = 0.0
        self._spk_level = self._spk_display = 0.0
        self._phase = 0.0
        self._muted = False
        self.update()

    def _tick(self) -> None:
        self._mic_display = max(self._mic_level, self._mic_display * self.DECAY)
        self._spk_display = max(self._spk_level, self._spk_display * self.DECAY)
        self._mic_level *= 0.5
        self._spk_level *= 0.5
        self._phase += 0.18
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        c = colors()
        level = max(self._mic_display, self._spk_display)
        quiet = self._muted and self._spk_display < 0.01
        tint = QColor(c["TEXT_SECONDARY"] if quiet else c["ACCENT_BRAND"])
        center = QPointF(self.width() / 2, self.height() / 2)

        if not quiet:
            glow = QRadialGradient(QPointF(0, 0), 90)
            tint.setAlpha(18 + int(level * 30))
            glow.setColorAt(0, tint)
            tint.setAlpha(0)
            glow.setColorAt(1, tint)
            painter.save()
            painter.translate(center)
            painter.scale(1, 0.32)
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(0, 0), 90, 90)
            painter.restore()

        # At rest, a small static mark; only actual audio makes it grow.
        count, spacing, width = 17, 8, 3
        left = center.x() - (count - 1) * spacing / 2
        for index in range(count):
            envelope = math.sin(math.pi * (index + 1) / (count + 1))
            motion = 0.45 + 0.55 * abs(math.sin(self._phase + index * 0.65))
            height = 3 + envelope * (4 + level * 42 * motion)
            tint.setAlpha(int((65 if quiet else 90) + envelope * 140))
            painter.setBrush(tint)
            painter.drawRoundedRect(
                QRectF(left + index * spacing, center.y() - height / 2, width, height),
                width / 2,
                width / 2,
            )
        painter.end()
