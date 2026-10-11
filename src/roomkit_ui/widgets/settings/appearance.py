"""Accessible theme choices with miniature previews painted by Qt."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QRadioButton, QSizePolicy, QWidget

from roomkit_ui.widgets.settings.choice_cards import paint_choice_indicator
from roomkit_ui.widgets.settings.style import settings_colors


class ThemeOption(QRadioButton):
    def __init__(self, theme: str, title: str) -> None:
        super().__init__(title)
        self.theme = theme
        self.setMinimumSize(160, 174)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleDescription(f"Apply the {title.lower()} theme immediately.")

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        c = settings_colors()
        preview = settings_colors(self.theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        frame = QRectF(3, 3, self.width() - 6, 132)
        painter.setPen(QPen(QColor(c["accent"] if self.isChecked() else c["border"]), 2))
        painter.setBrush(QColor(c["selected"] if self.isChecked() else c["soft"]))
        painter.drawRoundedRect(frame, 9, 9)
        self._paint_preview(painter, frame.adjusted(16, 15, -16, 0), preview)
        painter.setPen(QColor(c["text"]))
        painter.drawText(QRectF(4, 144, self.width() - 34, 24), Qt.AlignVCenter, self.text())
        paint_choice_indicator(painter, QRectF(self.width() - 23, 148, 16, 16), self.isChecked())
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(c["accent"]), 1, Qt.DotLine))
            painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 9, 9)
        painter.end()

    @staticmethod
    def _paint_preview(painter: QPainter, rect: QRectF, c: dict[str, str]) -> None:
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.setBrush(QColor(c["surface"]))
        painter.drawRoundedRect(rect.adjusted(0, 0, 0, 6), 5, 5)
        sidebar = QRectF(rect.x() + 1, rect.y() + 1, rect.width() * 0.29, rect.height())
        painter.fillRect(sidebar, QColor(c["sidebar"]))
        painter.setPen(Qt.NoPen)
        for row in range(3):
            painter.setBrush(QColor(c["selected"] if row == 0 else c["border"]))
            painter.drawRoundedRect(
                QRectF(sidebar.x() + 7, sidebar.y() + 26 + row * 13, sidebar.width() - 14, 5),
                2,
                2,
            )
        x = sidebar.right() + 12
        width = rect.right() - x - 12
        painter.setBrush(QColor(c["muted"]))
        painter.drawRoundedRect(QRectF(x, rect.y() + 20, width * 0.5, 4), 2, 2)
        painter.setBrush(QColor(c["soft"]))
        painter.setPen(QPen(QColor(c["border"]), 1))
        for y in (37, 65):
            painter.drawRoundedRect(QRectF(x, rect.y() + y, width, 18), 3, 3)
        painter.restore()


class ThemePicker(QWidget):
    theme_changed = Signal(str)

    def __init__(self, current: str) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.group = QButtonGroup(self)
        self.options: dict[str, ThemeOption] = {}
        for theme, title in (("light", "Light"), ("dark", "Dark")):
            option = ThemeOption(theme, title)
            self.group.addButton(option)
            self.options[theme] = option
            layout.addWidget(option)
        self.options.get(current, self.options["dark"]).setChecked(True)
        self.group.buttonToggled.connect(self._on_toggled)

    def _on_toggled(self, button: ThemeOption, checked: bool) -> None:
        if checked:
            self.theme_changed.emit(button.theme)

    def value(self) -> str:
        return next(theme for theme, button in self.options.items() if button.isChecked())
