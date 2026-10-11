"""Installed skills with local filtering and explicit enabled states."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.widgets.settings.catalog_controls import CatalogNotice, EmptyState, mark_dividers
from roomkit_ui.widgets.settings.controls import FeedbackLabel, label
from roomkit_ui.widgets.settings.search import normalized
from roomkit_ui.widgets.settings.skills.widgets import SkillCard


class MySkillsTab(QWidget):
    def __init__(
        self, *, on_skill_toggled, on_refresh, on_add_source, on_browse_marketplace, parent=None
    ) -> None:
        super().__init__(parent)
        self._cb_skill_toggled = on_skill_toggled
        self._cards: list[SkillCard] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        heading = QHBoxLayout()
        heading.addWidget(label("Agent skills", "settingsSectionTitle"), 1)
        self.browse_marketplace = QPushButton("Browse skills.sh")
        self.browse_marketplace.setObjectName("settingsPrimary")
        self.browse_marketplace.setAutoDefault(False)
        self.browse_marketplace.clicked.connect(on_browse_marketplace)
        heading.addWidget(self.browse_marketplace)
        self.add_source = QPushButton("+ Add skill source")
        self.add_source.setAutoDefault(False)
        self.add_source.clicked.connect(on_add_source)
        heading.addWidget(self.add_source)
        layout.addLayout(heading)
        layout.addWidget(
            label("Reusable instructions for tasks your assistant performs.", "settingsHint")
        )
        self._filters = QWidget()
        search_row = QHBoxLayout(self._filters)
        search_row.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find an installed skill…")
        self.search.setAccessibleName("Find an installed skill")
        self.search.setClearButtonEnabled(True)
        search_row.addWidget(self.search, 1)
        self.availability = QComboBox()
        self.availability.setAccessibleName("Skill activation status")
        for title, value in (("All skills", ""), ("Enabled", "enabled"), ("Disabled", "disabled")):
            self.availability.addItem(title, value)
        search_row.addWidget(self.availability)
        layout.addWidget(self._filters)
        self._summary_row = QWidget()
        summary_row = QHBoxLayout(self._summary_row)
        summary_row.setContentsMargins(0, 0, 0, 0)
        self.summary = label("", "settingsHint")
        summary_row.addWidget(self.summary, 1)
        self.refresh_button = QPushButton("Refresh skills")
        self.refresh_button.setAutoDefault(False)
        self.refresh_button.clicked.connect(on_refresh)
        summary_row.addWidget(self.refresh_button)
        layout.addWidget(self._summary_row)
        self._feedback = FeedbackLabel()
        layout.addWidget(self._feedback)
        self.empty = EmptyState(
            "No skills found",
            "Add a local source or a Git repository to discover skills.",
            "+ Add skill source",
            "sparkles",
        )
        self.empty.activated.connect(on_add_source)
        layout.addWidget(self.empty)
        self.no_matches = label(
            "No matching skills. Clear the search or change the filter.", "settingsHint"
        )
        layout.addWidget(self.no_matches)
        self._container = QFrame()
        self._container.setObjectName("settingsCard")
        self._flow = QVBoxLayout(self._container)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self._flow.setSpacing(0)
        layout.addWidget(self._container)
        layout.addWidget(
            CatalogNotice(
                "Skills supply instructions. "
                "Enabling a skill does not grant a connection or install a model.",
            )
        )
        self.search.textChanged.connect(self._filter)
        self.availability.currentIndexChanged.connect(self._filter)

    def refresh(self, sources: list[dict], enabled: set[str]) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._cards.clear()
        self._feedback.set_status("")
        try:
            from roomkit_ui.skill_manager import discover_all_skills

            skills = discover_all_skills(sources)
        except Exception as exc:
            skills = []
            self._feedback.set_status(f"Could not read skills: {exc}", "error")
        for meta, _path, source in skills:
            card = SkillCard(
                name=meta.name,
                description=meta.description,
                source_label=source,
                checked=meta.name in enabled,
            )
            if card.checkbox is not None:
                card.checkbox.toggled.connect(
                    lambda checked, n=meta.name: self._toggled(n, checked)
                )
            self._flow.addWidget(card)
            self._cards.append(card)
        self._filter()

    def _toggled(self, name: str, enabled: bool) -> None:
        self._cb_skill_toggled(name, enabled)
        self._filter()

    def _filter(self) -> None:
        words = normalized(self.search.text()).split()
        state = self.availability.currentData()
        visible = 0
        enabled = 0
        for card in self._cards:
            checked = card.checkbox is not None and card.checkbox.isChecked()
            matches = all(word in normalized(card.name) for word in words) and (
                not state or checked == (state == "enabled")
            )
            card.setVisible(matches)
            visible += matches
            enabled += checked
        self.summary.setText(f"{visible} skills shown · {enabled} enabled")
        populated = bool(self._cards)
        self.empty.setVisible(not populated)
        self.no_matches.setVisible(populated and visible == 0)
        self._container.setVisible(visible > 0)
        self._filters.setVisible(populated)
        self._summary_row.setVisible(populated)
        self.add_source.setVisible(populated)
        mark_dividers(self._cards)
