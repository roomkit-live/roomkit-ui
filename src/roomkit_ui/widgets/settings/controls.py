"""Reusable native sections, setting rows, switches and disclosures."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.widgets.settings.style import settings_colors


def label(text: str, name: str, *, wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def page_layout(page: QWidget, title: str, description: str) -> QVBoxLayout:
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(28)
    heading = QVBoxLayout()
    heading.setSpacing(6)
    heading.addWidget(label(title, "settingsPageTitle"))
    heading.addWidget(label(description, "settingsDescription"))
    layout.addLayout(heading)
    return layout


def navigation_link(text: str) -> QPushButton:
    button = QPushButton(text.replace("&", "&&"))
    button.setObjectName("settingsLink")
    button.setAutoDefault(False)
    button.setCursor(Qt.PointingHandCursor)
    return button


class SettingsForm(QVBoxLayout):
    """Labels above fields, with each control retaining its native minimum height."""

    def __init__(self, parent: QWidget | None = None) -> None:
        if parent is None:
            super().__init__()
        else:
            super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(10)

    def addRow(self, title: str | QWidget, field: QWidget | None = None) -> None:  # noqa: N802
        if isinstance(title, str):
            title = QLabel(title)
        if isinstance(title, QLabel) and field is not None:
            title.setBuddy(field)
        self.addWidget(title)
        if field is not None:
            field.setProperty("settingsFormField", True)
            self.addWidget(field)


class FeedbackLabel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("settingsFeedback")
        self.setWordWrap(True)
        self.setTextFormat(Qt.PlainText)
        self.hide()

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.setVisible(bool(text))

    def set_status(self, text: str, tone: str = "neutral") -> None:
        self.setText(text)
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class SettingsTabs(QWidget):
    """Keyboard-accessible tabs whose height follows only the visible content."""

    current_changed = Signal(int)

    def __init__(self, pages: list[tuple[str, QWidget]]) -> None:
        super().__init__()
        self._pages = [page for _, page in pages]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        self.bar = QTabBar()
        self.bar.setObjectName("settingsTabs")
        self.bar.setExpanding(False)
        self.bar.setDrawBase(False)
        header = QFrame()
        header.setObjectName("settingsTabHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self.bar)
        layout.addWidget(header)
        for title, page in pages:
            self.bar.addTab(title.replace("&", "&&"))
            layout.addWidget(page)
        self.bar.currentChanged.connect(self._select)
        self._select(0)

    def _select(self, index: int) -> None:
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)
        self.current_changed.emit(index)


class SettingRow(QFrame):
    def __init__(self, title: str, description: str, control: QWidget) -> None:
        super().__init__()
        self.setObjectName("settingsRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(20)
        copy = QVBoxLayout()
        copy.setSpacing(4)
        title_label = label(title, "settingsRowTitle")
        title_label.setBuddy(control)
        copy.addWidget(title_label)
        if description:
            copy.addWidget(label(description, "settingsHint"))
        layout.addLayout(copy, 1)
        control.setAccessibleName(title)
        control.setAccessibleDescription(description)
        layout.addWidget(control, 0, Qt.AlignVCenter)


class SettingsSection(QWidget):
    def __init__(self, title: str, description: str = "") -> None:
        super().__init__()
        self.setObjectName("settingsSection")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addWidget(label(title, "settingsSectionTitle"))
        if description:
            self._layout.addWidget(label(description, "settingsHint"))
        self._layout.addSpacing(6)
        self.card = QFrame()
        self.card.setObjectName("settingsCard")
        self.content = QVBoxLayout(self.card)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(0)
        self._layout.addWidget(self.card)

    def add_row(self, title: str, description: str, control: QWidget) -> None:
        self.add_widget(SettingRow(title, description, control))

    def add_widget(self, widget: QWidget) -> None:
        if self.content.count():
            separator = QFrame()
            separator.setObjectName("settingsSeparator")
            separator.setFixedHeight(1)
            self.content.addWidget(separator)
        self.content.addWidget(widget)


class StatusBadge(QLabel):
    """A compact status whose meaning is also readable without its color."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("settingsStatus")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_status(self, text: str, tone: str = "neutral") -> None:
        self.setText(text)
        if self.property("tone") != tone:
            self.setProperty("tone", tone)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()


class SettingsToggle(QCheckBox):
    """A switch drawing with QCheckBox's keyboard and accessibility behavior."""

    def __init__(self, text: str, checked: bool = False) -> None:
        super().__init__(text)
        self.setAccessibleName(text)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(48, 32)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        c = settings_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(c["accent"] if self.isChecked() else c["outline"]))
        painter.drawRoundedRect(QRectF(5, 6, 38, 20), 10, 10)
        painter.setBrush(QColor(c["surface"] if self.isChecked() else "#FFFFFF"))
        painter.drawEllipse(QRectF(26 if self.isChecked() else 8, 9, 14, 14))
        if self.hasFocus():
            painter.setPen(QPen(QColor(c["accent"]), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(1, 2, 46, 28), 13, 13)
        painter.end()


class AdvancedSection(QWidget):
    def __init__(self, title: str, content: QWidget, *, expanded: bool = False) -> None:
        super().__init__()
        self._title = title
        self.content = content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.button = QPushButton()
        self.button.setObjectName("settingsDisclosure")
        self.button.setCheckable(True)
        self.button.setAutoDefault(False)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setAccessibleName(title)
        layout.addWidget(self.button)
        layout.addWidget(content)
        self.button.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.button.setChecked(expanded)
        title = self._title.replace("&", "&&")  # QPushButton treats a single & as a mnemonic.
        self.button.setText(f"{'▾' if expanded else '▸'}  {title}")
        self.button.setAccessibleDescription("Expanded" if expanded else "Collapsed")
        self.content.setVisible(expanded)
