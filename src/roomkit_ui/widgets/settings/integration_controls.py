"""Shared searchable lists and detail navigation for Settings integrations."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.widgets.settings.catalog_controls import CatalogRow, EmptyState, mark_dividers
from roomkit_ui.widgets.settings.controls import StatusBadge, label
from roomkit_ui.widgets.settings.search import normalized


class DetailStack(QWidget):
    """Only the current view contributes to the page's minimum height."""

    def __init__(self) -> None:
        super().__init__()
        self._pages: list[QWidget] = []
        self._current = 0
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def addWidget(self, page: QWidget) -> None:  # noqa: N802
        self._layout.addWidget(page)
        self._pages.append(page)
        page.setVisible(len(self._pages) - 1 == self._current)

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        self._current = index
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)

    def currentIndex(self) -> int:  # noqa: N802
        return self._current


class _EntrySummary(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        copy = QVBoxLayout()
        copy.setSpacing(4)
        self.title = label("", "settingsRowTitle")
        self.detail = label("", "settingsHint")
        self.title.setTextFormat(Qt.PlainText)
        self.detail.setTextFormat(Qt.PlainText)
        copy.addWidget(self.title)
        copy.addWidget(self.detail)
        layout.addLayout(copy, 1)
        self.status = StatusBadge()
        layout.addWidget(self.status)


class _SummaryDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        option.text = ""  # The summary widget paints text; Qt still paints selection.


class _IntegrationItems(QListWidget):
    def keyPressEvent(self, event) -> None:  # noqa: N802
        item = self.currentItem()
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and item is not None:
            if not item.isHidden():
                self.itemActivated.emit(item)
            event.accept()
            return
        super().keyPressEvent(event)


class IntegrationList(QWidget):
    """Name search keeps model indices stable; actions work with mouse and keyboard."""

    add_requested = Signal()
    edit_requested = Signal(int)
    remove_requested = Signal(int)

    def __init__(self, title: str, description: str, singular: str) -> None:
        super().__init__()
        self._title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(label(description, "settingsHint"))
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Find {title.lower()} by name…")
        self.search.setAccessibleName(f"Find {title.lower()}")
        self.search.setClearButtonEnabled(True)
        toolbar.addWidget(self.search, 1)
        self.add_button = QPushButton(f"Add {singular}")
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(self.add_requested)
        toolbar.addWidget(self.add_button)
        layout.addLayout(toolbar)
        self.summary = label("", "settingsHint")
        layout.addWidget(self.summary)
        self.list = _IntegrationItems()
        self.list.setItemDelegate(_SummaryDelegate(self.list))
        self.list.setObjectName("settingsIntegrationList")
        self.list.setAccessibleName(title)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(lambda item: self.edit_requested.emit(self.list.row(item)))
        self.list.currentRowChanged.connect(self._selection_changed)
        layout.addWidget(self.list)
        self.empty = label("", "settingsDescription")
        layout.addWidget(self.empty)
        actions = QHBoxLayout()
        self.edit_button = QPushButton("Edit selected")
        self.remove_button = QPushButton("Remove selected")
        for button in (self.edit_button, self.remove_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.edit_button.clicked.connect(lambda: self.edit_requested.emit(self.list.currentRow()))
        self.remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.list.currentRow())
        )
        actions.addStretch()
        layout.addLayout(actions)
        self.search.textChanged.connect(self.refresh)
        self.refresh()

    def append(self, name: str, detail: str, status: str, tone: str = "neutral") -> None:
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 78))
        self.list.addItem(item)
        self.list.setItemWidget(item, _EntrySummary())
        self.update_entry(self.list.count() - 1, name, detail, status, tone)

    def update_entry(
        self, index: int, name: str, detail: str, status: str, tone: str = "neutral"
    ) -> None:
        item = self.list.item(index)
        if item is None:
            return
        item.setText(name)
        item.setData(Qt.AccessibleTextRole, f"{name}, {detail}, {status}")
        card = self.list.itemWidget(item)
        card.title.setText(name)
        card.detail.setText(detail)
        card.status.set_status(status, tone)
        self.refresh()

    def remove(self, index: int) -> None:
        item = self.list.item(index)
        if item is None:
            return
        card = self.list.itemWidget(item)
        self.list.takeItem(index)
        if card is not None:
            card.deleteLater()
        self.refresh()

    def refresh(self) -> None:
        words = normalized(self.search.text()).split()
        visible = 0
        for i in range(self.list.count()):
            item = self.list.item(i)
            matches = all(word in normalized(item.text()) for word in words)
            item.setHidden(not matches)
            visible += matches
        self.list.setVisible(visible > 0)
        self.list.setFixedHeight(min(5, max(1, visible)) * 80 + 4)
        self.summary.setText(f"{visible} of {self.list.count()} shown")
        self.empty.setText(
            "No matches. Try another name or clear the search."
            if self.list.count()
            else f"No {self._title.lower()} added yet. Use the Add button to get started."
        )
        self.empty.setVisible(visible == 0)
        self._selection_changed()

    def _selection_changed(self, _index: int = -1) -> None:
        item = self.list.currentItem()
        selected = item is not None and not item.isHidden()
        self.edit_button.setEnabled(selected)
        self.remove_button.setEnabled(selected)


class IntegrationCatalog(QWidget):
    """A single grouped card; each entry owns its edit and remove actions."""

    add_requested = Signal()
    edit_requested = Signal(int)
    remove_requested = Signal(int)

    def __init__(
        self,
        title: str,
        description: str,
        action: str,
        empty_title: str,
        empty_description: str,
        icon: str,
    ) -> None:
        super().__init__()
        self._icon = icon
        self.rows: list[CatalogRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        heading = QHBoxLayout()
        heading.addWidget(label(title, "settingsSectionTitle"), 1)
        self.add_button = QPushButton(action)
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(self.add_requested)
        heading.addWidget(self.add_button)
        layout.addLayout(heading)
        layout.addWidget(label(description, "settingsHint"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Find {title.lower()}…")
        self.search.setAccessibleName(f"Find {title.lower()}")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.card = QFrame()
        self.card.setObjectName("settingsCard")
        self._entries = QVBoxLayout(self.card)
        self._entries.setContentsMargins(0, 0, 0, 0)
        self._entries.setSpacing(0)
        layout.addWidget(self.card)
        self.empty = EmptyState(empty_title, empty_description, action, icon)
        self.empty.activated.connect(self.add_requested)
        layout.addWidget(self.empty)
        self.no_matches = EmptyState(
            "No matching entries", "Try another name or clear the search.", "Clear search", icon
        )
        self.no_matches.activated.connect(self.search.clear)
        layout.addWidget(self.no_matches)
        self.refresh()

    def append(self, name: str, detail: str, status: str, tone: str = "neutral") -> None:
        row = CatalogRow(icon=self._icon, removable=True)
        self.rows.append(row)
        self._entries.addWidget(row)
        row.manage.clicked.connect(lambda: self.edit_requested.emit(self.rows.index(row)))
        assert row.remove_button is not None
        row.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.rows.index(row)))
        self.update_entry(len(self.rows) - 1, name, detail, status, tone)

    def update_entry(
        self, index: int, name: str, detail: str, status: str, tone: str = "neutral"
    ) -> None:
        if 0 <= index < len(self.rows):
            self.rows[index].set_summary(name, detail, status, tone)
            self.refresh()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.rows):
            row = self.rows.pop(index)
            self._entries.removeWidget(row)
            row.hide()
            row.deleteLater()
            self.refresh()

    def refresh(self) -> None:
        words = normalized(self.search.text()).split()
        visible = 0
        for row in self.rows:
            matches = all(word in normalized(row.title.text()) for word in words)
            row.setVisible(matches)
            visible += matches
        populated = bool(self.rows)
        self.add_button.setVisible(populated)
        self.search.setVisible(populated)
        self.card.setVisible(visible > 0)
        self.empty.setVisible(not populated)
        self.no_matches.setVisible(populated and visible == 0)
        mark_dividers(self.rows)
