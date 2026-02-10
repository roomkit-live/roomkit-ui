"""Ambient glow VU meter with animated waveform — mic (green) + speaker (blue)."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from room_ui.theme import colors


class VUMeter(QWidget):
    """Full-width ambient glow that pulses with mic and speaker audio levels."""

    DECAY = 0.93
    GLOW_HEIGHT = 100

    # Glow layers: (alpha_base, radius_spread)
    _GLOW_LAYERS = [
        (0.50, 1.0),
        (0.25, 1.5),
        (0.10, 2.0),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.GLOW_HEIGHT)
        self.setMinimumWidth(100)

        self._mic_level = 0.0
        self._mic_display = 0.0
        self._spk_level = 0.0
        self._spk_display = 0.0
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 fps
        self._timer.timeout.connect(self._tick)

    # -- public API ----------------------------------------------------------

    def set_mic_level(self, level: float) -> None:
        self._mic_level = max(0.0, min(1.0, level))

    def set_speaker_level(self, level: float) -> None:
        self._spk_level = max(0.0, min(1.0, level))

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._mic_level = self._mic_display = 0.0
        self._spk_level = self._spk_display = 0.0
        self._phase = 0.0
        self.update()

    # -- animation -----------------------------------------------------------

    def _tick(self) -> None:
        # Attack: instant; Decay: exponential
        self._mic_display = (
            self._mic_level
            if self._mic_level > self._mic_display
            else self._mic_display * self.DECAY
        )
        self._spk_display = (
            self._spk_level
            if self._spk_level > self._spk_display
            else self._spk_display * self.DECAY
        )

        # Drain targets so missing frames decay
        self._mic_level *= 0.5
        self._spk_level *= 0.5

        # Advance wave phase
        self._phase += 0.10

        self.update()

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cy = h * 0.5

        # Background from theme
        p.fillRect(0, 0, w, h, QColor(colors()["BG_PRIMARY"]))

        mic = self._mic_display
        spk = self._spk_display

        # ── Radial glow: mic (green, left-of-center) ──
        if mic > 0.008:
            self._paint_glow(
                p, w, h,
                cx=w * 0.35, cy=cy,
                base_radius=w * 0.20 + w * 0.30 * mic,
                color_inner=QColor(48, 209, 88),
                color_outer=QColor(36, 180, 72),
                level=mic,
            )

        # ── Radial glow: speaker (blue → indigo, right-of-center) ──
        if spk > 0.008:
            self._paint_glow(
                p, w, h,
                cx=w * 0.65, cy=cy,
                base_radius=w * 0.20 + w * 0.30 * spk,
                color_inner=QColor(10, 132, 255),
                color_outer=QColor(94, 92, 230),
                level=spk,
            )

        # ── Waveform: mic (left half) ──
        if mic > 0.015:
            self._paint_wave(
                p, w, h, cy,
                x0=int(w * 0.04), x1=int(w * 0.50),
                level=mic,
                color=QColor(48, 209, 88),
                freq=8.0,
                phase_offset=0.0,
            )

        # ── Waveform: speaker (right half) ──
        if spk > 0.015:
            self._paint_wave(
                p, w, h, cy,
                x0=int(w * 0.50), x1=int(w * 0.96),
                level=spk,
                color=QColor(10, 132, 255),
                freq=6.0,
                phase_offset=math.pi * 0.5,
            )

        # ── Thin centre rule (subtle, always visible when active) ──
        any_level = max(mic, spk)
        if any_level > 0.008:
            a = int(30 + 40 * any_level)
            p.setPen(QPen(QColor(255, 255, 255, a), 0.5))
            p.drawLine(0, int(cy), w, int(cy))

        # ── Edge fade: blend into surrounding background ──
        bg = QColor(colors()["BG_PRIMARY"])
        fade_h = int(h * 0.35)
        p.setPen(Qt.NoPen)

        # Top fade
        top_grad = QLinearGradient(0, 0, 0, fade_h)
        bg_opaque = QColor(bg)
        bg_opaque.setAlpha(255)
        bg_transparent = QColor(bg)
        bg_transparent.setAlpha(0)
        top_grad.setColorAt(0.0, bg_opaque)
        top_grad.setColorAt(1.0, bg_transparent)
        p.setBrush(top_grad)
        p.drawRect(0, 0, w, fade_h)

        # Bottom fade
        bot_grad = QLinearGradient(0, h - fade_h, 0, h)
        bot_grad.setColorAt(0.0, bg_transparent)
        bot_grad.setColorAt(1.0, bg_opaque)
        p.setBrush(bot_grad)
        p.drawRect(0, h - fade_h, w, fade_h)

        p.end()

    # -- helpers -------------------------------------------------------------

    def _paint_glow(
        self,
        p: QPainter,
        w: float,
        h: float,
        cx: float,
        cy: float,
        base_radius: float,
        color_inner: QColor,
        color_outer: QColor,
        level: float,
    ) -> None:
        """Paint concentric radial gradient glow layers."""
        p.setPen(Qt.NoPen)
        for alpha_base, spread in self._GLOW_LAYERS:
            r = base_radius * spread
            grad = QRadialGradient(cx, cy, r)
            a = int(255 * alpha_base * level)
            ci = QColor(color_inner)
            ci.setAlpha(a)
            cm = QColor(
                (color_inner.red() + color_outer.red()) // 2,
                (color_inner.green() + color_outer.green()) // 2,
                (color_inner.blue() + color_outer.blue()) // 2,
                a // 3,
            )
            co = QColor(color_outer)
            co.setAlpha(0)
            grad.setColorAt(0.0, ci)
            grad.setColorAt(0.45, cm)
            grad.setColorAt(1.0, co)
            p.setBrush(grad)
            p.drawRect(0, 0, int(w), int(h))

    def _paint_wave(
        self,
        p: QPainter,
        w: int,
        h: int,
        cy: float,
        x0: int,
        x1: int,
        level: float,
        color: QColor,
        freq: float,
        phase_offset: float,
    ) -> None:
        """Paint an animated sine wave with tapered envelope."""
        span = max(x1 - x0, 1)
        amp = h * 0.30 * level
        step = 2

        # Primary wave
        path = QPainterPath()
        first = True
        for x in range(x0, x1, step):
            t = (x - x0) / span
            envelope = math.sin(t * math.pi)  # taper at edges
            y = cy + amp * envelope * math.sin(t * freq * math.pi + self._phase + phase_offset)
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)

        c1 = QColor(color)
        c1.setAlpha(int(180 * min(level * 1.5, 1.0)))
        p.setPen(QPen(c1, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # Secondary harmonic (thinner, faster, more transparent)
        path2 = QPainterPath()
        first = True
        for x in range(x0, x1, step):
            t = (x - x0) / span
            envelope = math.sin(t * math.pi)
            y = cy + amp * 0.5 * envelope * math.sin(
                t * freq * 1.7 * math.pi + self._phase * 1.4 + phase_offset
            )
            if first:
                path2.moveTo(x, y)
                first = False
            else:
                path2.lineTo(x, y)

        c2 = QColor(color)
        c2.setAlpha(int(90 * min(level * 1.5, 1.0)))
        p.setPen(QPen(c2, 1.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path2)
