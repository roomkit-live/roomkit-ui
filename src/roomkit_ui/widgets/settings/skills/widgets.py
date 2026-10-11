"""Skill rows shared by the installed catalogue and marketplace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout

from roomkit_ui.widgets.settings.catalog_controls import CatalogSymbol
from roomkit_ui.widgets.settings.controls import SettingsToggle, StatusBadge, label


class SkillCard(QFrame):
    def __init__(
        self,
        *,
        name: str,
        description: str,
        source_label: str = "",
        checked: bool = False,
        marketplace: bool = False,
        installed: bool = False,
        downloads: int = 0,
        version: str | None = None,
        slug: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard" if marketplace else "settingsCatalogRow")
        self.slug = slug
        self.name = name
        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)
        outer.addWidget(CatalogSymbol("sparkles"), 0, Qt.AlignTop)
        layout = QVBoxLayout()
        outer.addLayout(layout, 1)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = label(name, "settingsRowTitle")
        title.setTextFormat(Qt.PlainText)
        header.addWidget(title, 1)
        self.checkbox: SettingsToggle | None = None
        self.action_btn: QPushButton | None = None
        if marketplace:
            self.action_btn = QPushButton()
            self.action_btn.setAutoDefault(False)
            self.action_btn.setAccessibleName(f"Install {name}")
            self.action_btn.setCursor(Qt.PointingHandCursor)
            header.addWidget(self.action_btn)
            self.set_install_state("installed" if installed else "available")
        else:
            self.status = StatusBadge()
            header.addWidget(self.status)
            self.checkbox = SettingsToggle(f"Enable {name}", checked)
            self.checkbox.toggled.connect(self._show_enabled)
            header.addWidget(self.checkbox)
            self._show_enabled(checked)
        layout.addLayout(header)
        if description:
            summary = label(description, "settingsHint")
            summary.setTextFormat(Qt.PlainText)
            layout.addWidget(summary)
        details = []
        if source_label:
            details.append(source_label)
        if downloads:
            details.append(f"{format_count(downloads)} installs")
        if version:
            details.append(f"v{version}")
        if details:
            source = label(" · ".join(details), "settingsHint")
            source.setTextFormat(Qt.PlainText)
            layout.addWidget(source)

    def _show_enabled(self, checked: bool) -> None:
        self.status.set_status(
            "Enabled" if checked else "Disabled", "success" if checked else "neutral"
        )

    def set_install_state(self, state: str) -> None:
        if self.action_btn is not None:
            self.action_btn.setText(
                {
                    "available": "Install",
                    "installing": "Installing...",
                    "installed": "Installed ✓",
                    "error": "Retry",
                }[state]
            )
            self.action_btn.setEnabled(state in {"available", "error"})


def format_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
