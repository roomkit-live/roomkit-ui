"""Filterable local model library; downloads survive navigation and dialog closure."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from roomkit_ui.widgets.settings.controls import SettingsSection, label, navigation_link
from roomkit_ui.widgets.settings.model_jobs import model_downloads
from roomkit_ui.widgets.settings.model_library import LibraryModel, model_groups
from roomkit_ui.widgets.settings.models_widgets import _ModelRow
from roomkit_ui.widgets.settings.search import normalized


class _ModelsPage(QWidget):
    components_requested = Signal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._runner = model_downloads()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        intro = QVBoxLayout()
        intro.setSpacing(6)
        intro.addWidget(
            label(
                "Model files run on your device. Downloads continue when you close Settings. "
                "Use them in Conversation, Dictation, Audio & voice or Wake Word.",
                "settingsHint",
            )
        )
        self.components_link = navigation_link("Check required components →")
        self.components_link.clicked.connect(self.components_requested)
        intro.addWidget(self.components_link, 0, Qt.AlignLeft)
        layout.addLayout(intro)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a model…")
        self.search.setAccessibleName("Find a local model")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        filters = QHBoxLayout()
        self.category = QComboBox()
        self.category.setAccessibleName("Model category")
        self.category.addItem("All categories", "")
        self.availability = QComboBox()
        self.availability.setAccessibleName("Model download status")
        for title, key in (
            ("All models", ""),
            ("Downloaded", "downloaded"),
            ("To download", "available"),
        ):
            self.availability.addItem(title, key)
        filters.addWidget(self.category)
        filters.addWidget(self.availability)
        filters.addStretch()
        layout.addLayout(filters)
        self.summary = label("", "settingsHint")
        summary = QHBoxLayout()
        summary.addWidget(self.summary, 1)
        self.reset = navigation_link("Clear filters")
        self.reset.clicked.connect(self.clear_filters)
        summary.addWidget(self.reset)
        layout.addLayout(summary)
        self._groups = model_groups()
        self._sections: dict[str, SettingsSection] = {}
        self.rows: dict[str, _ModelRow] = {}
        for group in self._groups:
            self.category.addItem(group.title, group.key)
            section = SettingsSection(group.title, group.description)
            self._sections[group.key] = section
            for model in group.models:
                row = _ModelRow(model)
                row.action_btn.clicked.connect(
                    lambda _checked=False, m=model: self._runner.start(m)
                )
                row.delete_btn.clicked.connect(lambda _checked=False, m=model: self._delete(m))
                section.content.addWidget(row)
                self.rows[model.id] = row
            layout.addWidget(section)
        self.empty = label(
            "No models match these filters. Try another name or category.", "settingsDescription"
        )
        layout.addWidget(self.empty)
        self.search.textChanged.connect(self._filter)
        self.category.currentIndexChanged.connect(self._filter)
        self.availability.currentIndexChanged.connect(self._filter)
        self._runner.changed.connect(self._download_changed)
        self.refresh()

    def clear_filters(self) -> None:
        self.search.clear()
        self.category.setCurrentIndex(0)
        self.availability.setCurrentIndex(0)

    def refresh(self) -> None:
        for key, row in self.rows.items():
            row.refresh(self._runner.states.get(key))
        self._filter()

    @Slot(str)
    def _download_changed(self, model_id: str) -> None:
        if model_id in self.rows:
            self.rows[model_id].refresh(self._runner.states.get(model_id))
            self._filter()

    def _delete(self, model: LibraryModel) -> None:
        state = self._runner.states.get(model.id)
        if state and state.phase in {"resolving", "downloading"}:
            return
        try:
            model.delete()
        except OSError as exc:
            self.rows[model.id].error.setText(f"Could not delete files: {exc}")
            self.rows[model.id].error.show()
            return
        self._runner.clear(model.id)

    def _filter(self) -> None:
        words = normalized(self.search.text()).split()
        category = self.category.currentData()
        status = self.availability.currentData()
        visible = 0
        for group in self._groups:
            count = 0
            for model in group.models:
                row = self.rows[model.id]
                text = normalized(f"{model.name} {model.id} {model.detail} {group.title}")
                matches = (
                    (not category or category == group.key)
                    and all(word in text for word in words)
                    and (
                        not status
                        or row.phase == status
                        or (status == "available" and row.phase != "downloaded")
                    )
                )
                row.setVisible(matches)
                count += matches
            self._sections[group.key].setVisible(count > 0)
            visible += count
        downloaded = sum(row.phase == "downloaded" for row in self.rows.values())
        active = sum(row.phase in {"resolving", "downloading"} for row in self.rows.values())
        self.summary.setText(
            f"{visible} models shown · {downloaded} downloaded"
            + (f" · {active} downloading" if active else "")
        )
        self.empty.setVisible(visible == 0)
        self.reset.setVisible(bool(words or category or status))
