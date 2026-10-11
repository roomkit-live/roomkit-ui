"""Grouped keyboard-accessible navigation using stable page IDs."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from roomkit_ui.icons import svg_icon
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.widgets.settings.controls import label
from roomkit_ui.widgets.settings.page_registry import PageSpec
from roomkit_ui.widgets.settings.style import settings_colors


class SettingsNavigation(QListWidget):
    page_selected = Signal(str)

    def __init__(self, specs: tuple[PageSpec, ...]) -> None:
        super().__init__()
        self.setObjectName("settingsNavigation")
        self.setAccessibleName("Settings sections")
        self.setFrameShape(QListWidget.NoFrame)
        self.setIconSize(QSize(18, 18))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._items: dict[str, QListWidgetItem] = {}
        self._specs = specs
        group = ""
        for spec in specs:
            if spec.group != group:
                group = spec.group
                heading = QListWidgetItem()
                heading.setFlags(Qt.NoItemFlags)
                heading.setSizeHint(QSize(0, 36))
                self.addItem(heading)
                self.setItemWidget(heading, label(group.upper(), "settingsNavGroup", wrap=False))
            item = QListWidgetItem(spec.title)
            item.setData(Qt.UserRole, spec.key)
            item.setSizeHint(QSize(0, 36))
            self.addItem(item)
            self._items[spec.key] = item
        self.currentItemChanged.connect(self._on_item_changed)
        bind_theme(self, self._refresh_icons)

    def _refresh_icons(self) -> None:
        c = settings_colors()
        for spec in self._specs:
            glyph = svg_icon(spec.icon, c["muted"], 18)
            selected = svg_icon(spec.icon, c["accent"], 18)
            glyph.addPixmap(selected.pixmap(18, 18), QIcon.Selected)
            self._items[spec.key].setIcon(glyph)

    def select_page(self, key: str) -> None:
        item = self._items[key]
        self.setCurrentItem(item)
        self.scrollToItem(item)

    def _on_item_changed(self, item: QListWidgetItem, _previous: QListWidgetItem) -> None:
        if item is not None and (key := item.data(Qt.UserRole)):
            self.page_selected.emit(key)
