"""Control bar: sparkle center button with glow, context-aware side buttons."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from room_ui.icons import svg_icon
from room_ui.theme import colors

# ---------------------------------------------------------------------------
# Base circle button
# ---------------------------------------------------------------------------


class _PillButton(QPushButton):
    """Rounded-rectangle (pill) button with custom painted background."""

    def __init__(
        self,
        btn_width: int,
        btn_height: int,
        padding: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._btn_w = btn_width
        self._btn_h = btn_height
        self._radius = btn_height / 2.0
        self._padding = padding
        self._bg = QColor("#30D158")
        self._bg_hover = QColor("#28c04e")
        self._hover = False
        self.setFixedSize(btn_width + 2 * padding, btn_height + 2 * padding)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def set_bg(self, normal: str, hover: str) -> None:
        self._bg = QColor(normal)
        self._bg_hover = QColor(hover)
        self.update()

    def enterEvent(self, ev) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = self._bg_hover if self._hover else self._bg
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        rect = QRectF(
            self._padding + 1,
            self._padding + 1,
            self._btn_w - 2,
            self._btn_h - 2,
        )
        p.drawRoundedRect(rect, self._radius, self._radius)
        p.end()
        super().paintEvent(_ev)


# ---------------------------------------------------------------------------
# Center button with glow ring
# ---------------------------------------------------------------------------

_GLOW_COLORS = {
    "idle": "#30D158",
    "connecting": "#FF9F0A",
    "active": "#FF453A",
    "error": "#30D158",
}


class _CenterButton(_PillButton):
    """Rounded-rect center button with glow ring."""

    _BURST_DURATION = 0.40  # seconds
    _PULSE_MIN = 3.0
    _PULSE_MAX = 8.0

    def __init__(self, parent: QWidget | None = None) -> None:
        # 100×46 pill, 10 px padding → 120×66 widget
        super().__init__(btn_width=100, btn_height=46, padding=10, parent=parent)
        self._glow_color = QColor(_GLOW_COLORS["idle"])

        # Burst state
        self._burst_start: float | None = None

        # Pulse state
        self._pulsing = False
        self._pulse_t0 = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    # -- glow API -----------------------------------------------------------

    def set_glow_color(self, state: str) -> None:
        self._glow_color = QColor(_GLOW_COLORS.get(state, _GLOW_COLORS["idle"]))

    def trigger_burst(self) -> None:
        self._burst_start = time.monotonic()
        if not self._timer.isActive():
            self._timer.start()

    def start_pulse(self) -> None:
        self._pulsing = True
        self._pulse_t0 = time.monotonic()
        if not self._timer.isActive():
            self._timer.start()

    def stop_pulse(self) -> None:
        self._pulsing = False
        self._burst_start = None
        if self._timer.isActive():
            self._timer.stop()
        self.update()

    # -- internals ----------------------------------------------------------

    def _tick(self) -> None:
        now = time.monotonic()
        need_timer = self._pulsing
        if self._burst_start is not None:
            if now - self._burst_start > self._BURST_DURATION:
                self._burst_start = None
            else:
                need_timer = True
        if not need_timer:
            self._timer.stop()
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        half_h = self._btn_h / 2.0

        now = time.monotonic()

        # -- glow ring (pulse or burst) -------------------------------------
        glow_spread: float | None = None
        glow_alpha = 0.0

        if self._burst_start is not None:
            elapsed = now - self._burst_start
            t = min(elapsed / self._BURST_DURATION, 1.0)
            glow_spread = t * 14.0
            glow_alpha = 0.35 * (1.0 - t)

        elif self._pulsing:
            elapsed = now - self._pulse_t0
            phase = math.sin(elapsed * 3.0)  # ~0.33 Hz oscillation
            glow_spread = self._PULSE_MIN + (self._PULSE_MAX - self._PULSE_MIN) * (
                phase * 0.5 + 0.5
            )
            glow_alpha = 0.10 + 0.08 * (phase * 0.5 + 0.5)

        if glow_spread is not None and glow_alpha > 0.005:
            gc = QColor(self._glow_color)
            # Draw glow as a larger rounded rect behind the button
            glow_rect = QRectF(
                self._padding - glow_spread,
                self._padding - glow_spread,
                self._btn_w + glow_spread * 2,
                self._btn_h + glow_spread * 2,
            )
            glow_radius = half_h + glow_spread
            glow_color = QColor(gc.red(), gc.green(), gc.blue(), int(255 * glow_alpha))
            # Use a clipped path to create a ring (outer minus inner)
            outer = QPainterPath()
            outer.addRoundedRect(glow_rect, glow_radius, glow_radius)
            inner = QPainterPath()
            inner.addRoundedRect(
                QRectF(self._padding + 1, self._padding + 1, self._btn_w - 2, self._btn_h - 2),
                self._radius,
                self._radius,
            )
            ring = outer - inner
            p.setPen(Qt.NoPen)
            p.setBrush(glow_color)
            p.drawPath(ring)

        p.end()

        # Draw the filled pill + icon via parent
        super().paintEvent(ev)


# ---------------------------------------------------------------------------
# Side button (small circle with subtle drop shadow)
# ---------------------------------------------------------------------------


class _SideButton(QPushButton):
    """36 px circular side button with border and subtle drop shadow."""

    def __init__(self, diameter: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._hover = False
        self._muted = False  # used by context-button mute mode
        self.setFixedSize(diameter + 4, diameter + 4)  # extra room for shadow
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def enterEvent(self, ev) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = self._diameter
        c = colors()

        # Offset so circle is centered in widget with room for shadow below
        ox = (self.width() - d) // 2
        oy = (self.height() - d) // 2

        # Subtle drop shadow (1 px down, slightly transparent)
        shadow = QColor(0, 0, 0, 30)
        p.setPen(Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(ox, oy + 1, d, d)

        # Background + border
        if self._muted:
            bg = QColor(255, 69, 58, 60 if self._hover else 40)
            border = QColor(c["ACCENT_RED"])
        else:
            bg = QColor(c["SEPARATOR"] if self._hover else c["BG_TERTIARY"])
            border = QColor(c["SEPARATOR"])

        p.setPen(QPen(border, 1.5))
        p.setBrush(bg)
        p.drawEllipse(ox + 1, oy + 1, d - 2, d - 2)
        p.end()
        super().paintEvent(_ev)


# ---------------------------------------------------------------------------
# Context button (left) — switches between reset and mute modes
# ---------------------------------------------------------------------------


class _ContextButton(_SideButton):
    """Left button: 'reset' mode when idle/error, 'mute' mode in session."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(36, parent)
        self._mode = "reset"
        self._apply_reset_icon()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def muted(self) -> bool:
        return self._muted

    def set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._muted = False
        if mode == "reset":
            self._apply_reset_icon()
            self.setToolTip("Reset conversation")
        else:
            self._apply_mute_icon()
            self.setToolTip("Mute microphone")
        self.update()

    def toggle_mute(self) -> None:
        self._muted = not self._muted
        self._apply_mute_icon()
        self.update()

    def _apply_reset_icon(self) -> None:
        c = colors()
        self.setIcon(svg_icon("arrow-path", c["TEXT_SECONDARY"], 18))
        self.setIconSize(self.size() * 0.45)

    def _apply_mute_icon(self) -> None:
        c = colors()
        if self._muted:
            self.setIcon(svg_icon("microphone-slash", c["ACCENT_RED"], 18))
            self.setToolTip("Unmute microphone")
        else:
            self.setIcon(svg_icon("microphone", c["TEXT_PRIMARY"], 18))
            self.setToolTip("Mute microphone")


# ---------------------------------------------------------------------------
# Control bar
# ---------------------------------------------------------------------------

_BTN_COLORS = {
    "idle": ("#30D158", "#28c04e"),
    "connecting": ("#FF9F0A", "#E08F09"),
    "active": ("#FF453A", "#E03E34"),
    "error": ("#30D158", "#28c04e"),
}


class ControlBar(QWidget):
    """Bottom control bar — center sparkle button, context left, settings right."""

    start_requested = Signal()
    stop_requested = Signal()
    mute_toggled = Signal(bool)
    settings_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(72)
        self._is_active = False
        c = colors()

        # ── Left: context button (reset / mute) ──
        self._left_btn = _ContextButton()
        self._left_btn.clicked.connect(self._on_left_click)

        # ── Center: sparkle / stop ──
        self._center_btn = _CenterButton()
        self._center_btn.set_bg(*_BTN_COLORS["idle"])
        self._center_btn.setIcon(svg_icon("sparkles", "#FFFFFF", 24))
        self._center_btn.setIconSize(self._center_btn.size() * 0.30)
        self._center_btn.setToolTip("Start voice session")
        self._center_btn.clicked.connect(self._on_action)

        # ── Right: settings ──
        self._right_btn = _SideButton(36)
        self._right_btn.setIcon(svg_icon("cog-6-tooth", c["TEXT_SECONDARY"], 18))
        self._right_btn.setIconSize(self._right_btn.size() * 0.45)
        self._right_btn.setToolTip("Settings")
        self._right_btn.clicked.connect(self.settings_requested.emit)

        # ── Layout ──
        row = QHBoxLayout(self)
        row.setContentsMargins(24, 0, 24, 0)
        row.addWidget(self._left_btn, alignment=Qt.AlignVCenter)
        row.addStretch()
        row.addWidget(self._center_btn, alignment=Qt.AlignVCenter)
        row.addStretch()
        row.addWidget(self._right_btn, alignment=Qt.AlignVCenter)

    # -- public API ----------------------------------------------------------

    def set_state(self, state: str) -> None:
        normal, hover = _BTN_COLORS.get(state, _BTN_COLORS["idle"])
        self._center_btn.set_bg(normal, hover)
        self._center_btn.set_glow_color(state)

        if state in ("idle", "error"):
            self._is_active = False
            self._center_btn.setIcon(svg_icon("sparkles", "#FFFFFF", 24))
            self._center_btn.setIconSize(self._center_btn.size() * 0.30)
            self._center_btn.setToolTip("Start voice session")
            self._center_btn.stop_pulse()
            self._left_btn.set_mode("reset")
        elif state == "connecting":
            self._is_active = False
            self._center_btn.setIcon(svg_icon("stop", "#FFFFFF", 22))
            self._center_btn.setIconSize(self._center_btn.size() * 0.28)
            self._center_btn.setToolTip("Cancel")
            self._center_btn.start_pulse()
            self._left_btn.set_mode("mute")
        elif state == "active":
            self._is_active = True
            self._center_btn.setIcon(svg_icon("stop", "#FFFFFF", 22))
            self._center_btn.setIconSize(self._center_btn.size() * 0.28)
            self._center_btn.setToolTip("End voice session")
            self._center_btn.start_pulse()
            self._left_btn.set_mode("mute")

    def set_status_text(self, text: str) -> None:
        pass  # no status label in minimal bar

    # -- internal ------------------------------------------------------------

    def _on_action(self) -> None:
        self._center_btn.trigger_burst()
        if self._is_active:
            self.stop_requested.emit()
        else:
            self.start_requested.emit()

    def _on_left_click(self) -> None:
        if self._left_btn.mode == "reset":
            self.reset_requested.emit()
        else:
            self._left_btn.toggle_mute()
            self.mute_toggled.emit(self._left_btn.muted)
