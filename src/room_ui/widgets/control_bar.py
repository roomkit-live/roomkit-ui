"""Control bar: centered circle call button, mic mute toggle, status."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from room_ui.icons import svg_icon
from room_ui.theme import colors


class _CircleButton(QPushButton):
    """A perfectly round button with custom painted background."""

    def __init__(self, diameter: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._bg = QColor("#30D158")
        self._bg_hover = QColor("#28c04e")
        self._hover = False
        self.setFixedSize(diameter, diameter)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        # Override all QSS so we fully own painting
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
        p.drawEllipse(1, 1, self._diameter - 2, self._diameter - 2)
        p.end()
        # Let Qt paint the icon on top
        super().paintEvent(_ev)


class _MuteButton(QPushButton):
    """Circular mic-mute toggle with custom painting."""

    def __init__(self, diameter: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._muted = False
        self._hover = False
        self.setFixedSize(diameter, diameter)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, v: bool) -> None:
        self._muted = v
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
        d = self._diameter
        c = colors()

        if self._muted:
            # Red-tinted background
            bg = QColor(255, 69, 58, 40) if not self._hover else QColor(255, 69, 58, 60)
            border = QColor(c["ACCENT_RED"])
        else:
            bg = QColor(c["BG_TERTIARY"]) if not self._hover else QColor(c["SEPARATOR"])
            border = QColor(c["SEPARATOR"])

        p.setPen(QPen(border, 1.5))
        p.setBrush(bg)
        p.drawEllipse(2, 2, d - 4, d - 4)
        p.end()
        super().paintEvent(_ev)


class ControlBar(QWidget):
    """Bottom control bar with call-style circle button and mic toggle."""

    start_requested = Signal()
    stop_requested = Signal()
    mute_toggled = Signal(bool)
    settings_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(56)
        self._is_active = False
        c = colors()
        icon_color = c["TEXT_PRIMARY"]
        icon_secondary = c["TEXT_SECONDARY"]

        # ── Mic mute ──
        self._mute_btn = _MuteButton(36)
        self._mute_btn.setIcon(svg_icon("microphone", icon_color, 18))
        self._mute_btn.setIconSize(self._mute_btn.size() * 0.48)
        self._mute_btn.setToolTip("Mute microphone")
        self._mute_btn.clicked.connect(self._toggle_mute)

        # ── Main call button ──
        self._call_btn = _CircleButton(44)
        self._call_btn.set_bg(c["ACCENT_GREEN"], "#28c04e")
        self._call_btn.setIcon(svg_icon("phone", "#FFFFFF", 20))
        self._call_btn.setIconSize(self._call_btn.size() * 0.45)
        self._call_btn.setToolTip("Start voice session")
        self._call_btn.clicked.connect(self._on_action)

        # ── Reset button ──
        self._reset_btn = _MuteButton(36)
        self._reset_btn.setIcon(svg_icon("arrow-path", icon_secondary, 18))
        self._reset_btn.setIconSize(self._reset_btn.size() * 0.48)
        self._reset_btn.setToolTip("Reset conversation")
        self._reset_btn.clicked.connect(self.reset_requested.emit)

        # ── Settings button ──
        self._gear_btn = _MuteButton(36)
        self._gear_btn.setIcon(svg_icon("cog-6-tooth", icon_secondary, 18))
        self._gear_btn.setIconSize(self._gear_btn.size() * 0.48)
        self._gear_btn.setToolTip("Settings")
        self._gear_btn.clicked.connect(self.settings_requested.emit)

        # ── Layout ──
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 6, 20, 6)
        row.addWidget(self._mute_btn, alignment=Qt.AlignVCenter)
        row.addStretch()
        row.addWidget(self._call_btn, alignment=Qt.AlignVCenter)
        row.addStretch()
        row.addWidget(self._reset_btn, alignment=Qt.AlignVCenter)
        row.addWidget(self._gear_btn, alignment=Qt.AlignVCenter)

    # -- public API ----------------------------------------------------------

    def set_state(self, state: str) -> None:
        if state == "idle":
            self._is_active = False
            self._call_btn.set_bg("#30D158", "#28c04e")
            self._call_btn.setIcon(svg_icon("phone", "#FFFFFF", 20))
            self._call_btn.setToolTip("Start voice session")
        elif state == "connecting":
            self._is_active = False
            self._call_btn.set_bg("#FF9F0A", "#E08F09")
            self._call_btn.setIcon(svg_icon("stop", "#FFFFFF", 20))
            self._call_btn.setToolTip("Cancel")
        elif state == "active":
            self._is_active = True
            self._call_btn.set_bg("#FF453A", "#E03E34")
            self._call_btn.setIcon(svg_icon("stop", "#FFFFFF", 20))
            self._call_btn.setToolTip("End voice session")
        elif state == "error":
            self._is_active = False
            self._call_btn.set_bg("#30D158", "#28c04e")
            self._call_btn.setIcon(svg_icon("phone", "#FFFFFF", 20))
            self._call_btn.setToolTip("Start voice session")

    def set_status_text(self, text: str) -> None:
        pass  # no status label in minimal bar

    # -- internal ------------------------------------------------------------

    def _on_action(self) -> None:
        if self._is_active:
            self.stop_requested.emit()
        else:
            self.start_requested.emit()

    def _toggle_mute(self) -> None:
        c = colors()
        self._mute_btn.muted = not self._mute_btn.muted
        if self._mute_btn.muted:
            self._mute_btn.setIcon(svg_icon("microphone-slash", c["ACCENT_RED"], 20))
            self._mute_btn.setToolTip("Unmute microphone")
        else:
            self._mute_btn.setIcon(svg_icon("microphone", c["TEXT_PRIMARY"], 20))
            self._mute_btn.setToolTip("Mute microphone")
        self.mute_toggled.emit(self._mute_btn.muted)
