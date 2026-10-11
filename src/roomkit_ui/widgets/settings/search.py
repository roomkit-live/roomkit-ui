"""Searchable setting destinations; indexes labels and aliases, never entered values."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from roomkit_ui.widgets.settings.controls import label


@dataclass(frozen=True)
class SearchTarget:
    title: str
    keywords: str = ""
    control: str = ""
    tabs: tuple[tuple[str, int], ...] = ()
    disclosure: str = ""
    fallback: str = ""
    unavailable: str = ""


@dataclass(frozen=True)
class SearchResult:
    page: str
    page_title: str
    target: SearchTarget


def normalized(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )


def find_settings(specs, query: str) -> list[SearchResult]:
    words = normalized(query).split()
    if not words:
        return []
    matches = []
    for spec in specs:
        targets = (SearchTarget(spec.title), *spec.search)
        seen = set()
        for target in targets:
            title = normalized(target.title)
            if title in seen:
                continue
            seen.add(title)
            haystack = normalized(f"{spec.title} {target.title} {target.keywords}")
            if all(word in haystack for word in words):
                score = (
                    0
                    if normalized(query).strip() == title
                    else 1
                    if all(word in title for word in words)
                    else 2
                )
                matches.append(
                    (score, SearchResult(spec.key, f"{spec.group} / {spec.title}", target))
                )
    return [result for _, result in sorted(matches, key=lambda pair: pair[0])]


class SearchResults(QWidget):
    activated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)
        self.summary = label("", "settingsSectionTitle")
        layout.addWidget(self.summary)
        self.list = QListWidget()
        self.list.setObjectName("settingsSearchResults")
        self.list.setAccessibleName("Matching settings")
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(self._activate)
        self.list.itemClicked.connect(self._activate)
        layout.addWidget(self.list, 1)
        self.empty = label(
            "No matching settings. Try a provider name, microphone, memory or shortcut.",
            "settingsDescription",
        )
        self.empty.setAlignment(Qt.AlignTop)
        layout.addWidget(self.empty, 1)

    def show_results(self, results: list[SearchResult]) -> None:
        self.list.clear()
        for result in results:
            item = QListWidgetItem(f"{result.target.title}\n{result.page_title}")
            item.setData(Qt.UserRole, result)
            self.list.addItem(item)
        self.summary.setText(
            f"{len(results)} matching {'setting' if len(results) == 1 else 'settings'}"
        )
        self.list.setVisible(bool(results))
        self.empty.setVisible(not results)
        if results:
            self.list.setCurrentRow(0)

    def activate_current(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self._activate(item)

    def _activate(self, item: QListWidgetItem) -> None:
        self.activated.emit(item.data(Qt.UserRole))
