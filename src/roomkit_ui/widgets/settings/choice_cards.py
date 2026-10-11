"""Large native radio cards with the visual hierarchy of the Settings prototype."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.icons import svg_icon
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.widgets.settings.controls import label
from roomkit_ui.widgets.settings.style import settings_colors


def paint_choice_indicator(painter: QPainter, circle: QRectF, checked: bool) -> None:
    colors = settings_colors()
    painter.setPen(QPen(QColor(colors["accent"] if checked else colors["outline"]), 1))
    painter.setBrush(QColor(colors["accent"]) if checked else Qt.NoBrush)
    painter.drawEllipse(circle)
    if checked:
        painter.setPen(QPen(QColor(colors["surface"]), 1.5))
        x, y = circle.x(), circle.y()
        painter.drawLine(int(x + 4), int(y + 8), int(x + 7), int(y + 11))
        painter.drawLine(int(x + 7), int(y + 11), int(x + 12), int(y + 5))


class ChoiceCard(QRadioButton):
    def __init__(self, title: str, description: str, icon: str) -> None:
        super().__init__(title)
        self.setMinimumHeight(172)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        self.symbol = QLabel()
        self.symbol.setFixedSize(24, 24)
        layout.addWidget(self.symbol)
        layout.addWidget(label(title, "settingsChoiceTitle"))
        layout.addWidget(label(description, "settingsChoiceDescription"))
        layout.addStretch()
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        bind_theme(
            self,
            lambda: self.symbol.setPixmap(
                svg_icon(icon, settings_colors()["accent"], 24).pixmap(24, 24)
            ),
        )

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def sizeHint(self):  # noqa: N802
        return self.layout().sizeHint()

    def minimumSizeHint(self):  # noqa: N802
        return self.layout().minimumSize()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        colors = settings_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(colors["selected"] if self.isChecked() else colors["surface"]))
        painter.setPen(
            QPen(
                QColor(colors["accent"] if self.isChecked() else colors["border"]),
                2 if self.isChecked() else 1,
            )
        )
        painter.drawRoundedRect(QRectF(2, 2, self.width() - 4, self.height() - 4), 10, 10)
        paint_choice_indicator(painter, QRectF(self.width() - 38, 23, 16, 16), self.isChecked())
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(colors["accent"]), 1, Qt.DotLine))
            painter.drawRoundedRect(QRectF(6, 6, self.width() - 12, self.height() - 12), 7, 7)
        painter.end()


class ChoiceCards(QWidget):
    value_changed = Signal(str)

    def __init__(self, choices: list[tuple[str, str, str, str]], current: str) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.group = QButtonGroup(self)
        self.options: dict[str, ChoiceCard] = {}
        for value, title, description, icon in choices:
            card = ChoiceCard(title, description, icon)
            self.options[value] = card
            self.group.addButton(card)
            layout.addWidget(card, 1)
        self.set_value(current if current in self.options else choices[0][0])
        self.setFocusProxy(self.options[self.value()])
        self.group.buttonToggled.connect(self._toggled)

    def _toggled(self, button: ChoiceCard, checked: bool) -> None:
        if checked:
            self.setFocusProxy(button)
            self.value_changed.emit(self.value())

    def set_value(self, value: str) -> None:
        self.options[value].setChecked(True)

    def value(self) -> str:
        return next(value for value, card in self.options.items() if card.isChecked())
