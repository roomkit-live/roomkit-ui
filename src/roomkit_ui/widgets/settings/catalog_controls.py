"""Grouped Settings rows and actionable empty states matching the design reference."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.icons import svg_icon
from roomkit_ui.widgets.settings.controls import StatusBadge, label
from roomkit_ui.widgets.settings.style import settings_colors


class CatalogSymbol(QLabel):
    """An existing vector icon, recolored when the live theme changes."""

    def __init__(self, icon: str = "", text: str = "") -> None:
        super().__init__(text)
        self._icon = icon
        self.setObjectName("settingsCatalogSymbol")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(36, 36)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._icon:
            painter = QPainter(self)
            svg_icon(self._icon, settings_colors()["muted"], 22).paint(painter, 7, 7, 22, 22)
            painter.end()


class CatalogNotice(QFrame):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("settingsCatalogNotice")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(CatalogSymbol("information-circle"), 0, Qt.AlignTop)
        layout.addWidget(label(text, "settingsNoticeCopy"), 1)


class CatalogRow(QFrame):
    """Summary and actions stay on one line, wrapping actions in narrow windows."""

    def __init__(self, *, icon: str = "", symbol: str = "", removable: bool = False) -> None:
        super().__init__()
        self.setObjectName("settingsCatalogRow")
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(20, 18, 20, 18)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        self.grid.setColumnStretch(1, 1)
        self.symbol = CatalogSymbol(icon, symbol)
        self.grid.addWidget(self.symbol, 0, 0, Qt.AlignVCenter)
        copy = QVBoxLayout()
        copy.setSpacing(4)
        self.title = label("", "settingsRowTitle")
        self.description = label("", "settingsHint")
        for widget in (self.title, self.description):
            widget.setTextFormat(Qt.PlainText)
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            copy.addWidget(widget)
        self.grid.addLayout(copy, 0, 1)
        self.action_area = QWidget()
        self.action_area.setObjectName("settingsRow")
        actions = QHBoxLayout(self.action_area)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(12)
        self.status = StatusBadge()
        actions.addWidget(self.status)
        self.manage = QPushButton("Manage")
        self.manage.setAutoDefault(False)
        actions.addWidget(self.manage)
        self.remove_button: QPushButton | None = None
        if removable:
            self.remove_button = QPushButton("×")
            self.remove_button.setObjectName("settingsRemoveEntry")
            self.remove_button.setAutoDefault(False)
            self.remove_button.setToolTip("Remove entry")
            actions.addWidget(self.remove_button)
        self.grid.addWidget(self.action_area, 0, 2)
        self._narrow = False

    def set_summary(self, name: str, detail: str, status: str, tone: str = "neutral") -> None:
        self.title.setText(name)
        self.description.setText(detail)
        self.description.setVisible(bool(detail))
        self.status.set_status(status, tone)
        self.manage.setAccessibleName(f"Manage {name}")
        if self.remove_button is not None:
            self.remove_button.setAccessibleName(f"Remove {name}")
            self.remove_button.setToolTip(f"Remove {name}")
        self.setAccessibleName(f"{name}, {detail}, {status}")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        narrow = self.width() < 620
        if narrow != self._narrow:
            self._narrow = narrow
            self.grid.removeWidget(self.action_area)
            self.grid.addWidget(
                self.action_area,
                1 if narrow else 0,
                1 if narrow else 2,
                1,
                2 if narrow else 1,
                Qt.AlignRight,
            )


class EmptyState(QFrame):
    activated = Signal()

    def __init__(self, title: str, description: str, action: str, icon: str) -> None:
        super().__init__()
        self.setObjectName("settingsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(12)
        layout.addWidget(CatalogSymbol(icon), 0, Qt.AlignHCenter)
        self.title = label(title, "settingsRowTitle")
        self.description = label(description, "settingsHint")
        for widget in (self.title, self.description):
            widget.setAlignment(Qt.AlignCenter)
            layout.addWidget(widget)
        self.button = QPushButton(action)
        self.button.setObjectName("settingsPrimary")
        self.button.setAutoDefault(False)
        self.button.clicked.connect(self.activated)
        layout.addWidget(self.button, 0, Qt.AlignHCenter)
        self.setFocusProxy(self.button)


def mark_dividers(rows: Sequence[QWidget]) -> None:
    visible = [row for row in rows if not row.isHidden()]
    for row in rows:
        divider = bool(visible and row is not visible[-1])
        if row.property("divider") != divider:
            row.setProperty("divider", divider)
            row.style().unpolish(row)
            row.style().polish(row)
