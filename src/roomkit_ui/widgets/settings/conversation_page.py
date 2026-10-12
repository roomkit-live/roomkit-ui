"""Conversation setup and personality, with one owner for every setting."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QTextEdit, QVBoxLayout, QWidget

from roomkit_ui.widgets.settings.attitudes_page import _AttitudesPage
from roomkit_ui.widgets.settings.controls import (
    SettingsSection,
    SettingsTabs,
    label,
    navigation_link,
    page_layout,
)
from roomkit_ui.widgets.settings.voice_setup import VoiceSetup


class ConversationPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = page_layout(
            self, "Conversation", "Choose how your assistant listens, thinks, and speaks."
        )
        self.providers_link = navigation_link("Manage providers & keys →")
        self.providers_link.clicked.connect(lambda: self.navigate_requested.emit("providers"))
        self.models_link = navigation_link("Browse local models →")
        self.models_link.clicked.connect(lambda: self.navigate_requested.emit("models"))
        links = QHBoxLayout()
        links.addWidget(self.providers_link, 0, Qt.AlignLeft)
        links.addWidget(self.models_link, 0, Qt.AlignLeft)
        links.addStretch()
        self.voice = VoiceSetup(settings)
        self.voice.spoken_language_link.clicked.connect(
            lambda: self.navigate_requested.emit("general")
        )
        personality = QWidget()
        personality_layout = QVBoxLayout(personality)
        personality_layout.setContentsMargins(0, 0, 0, 0)
        personality_layout.setSpacing(28)
        instructions = SettingsSection(
            "Instructions", "The base instructions used for your conversations."
        )
        instructions.content.setContentsMargins(16, 16, 16, 16)
        self.prompt = QTextEdit()
        self.prompt.setAccessibleName("System instructions")
        self.prompt.setLineWrapMode(QTextEdit.WidgetWidth)
        self.prompt.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.prompt.setPlainText(
            settings.get(
                "system_prompt", "You are a friendly voice assistant. Be concise and helpful."
            )
        )
        self.prompt.setMinimumHeight(130)
        instructions.content.addWidget(self.prompt)
        selection = SettingsSection("Personality")
        self.attitude_combo = QComboBox()
        self.attitude_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.attitude_combo.setMinimumContentsLength(10)
        self._saved_attitude = settings.get("selected_attitude", "")
        selection.add_row(
            "Default personality",
            "Adds a communication style to your instructions.",
            self.attitude_combo,
        )
        self.personality_preview = label("", "settingsHint")
        self.personality_preview.setTextFormat(Qt.PlainText)
        self.personality_preview.setContentsMargins(20, 0, 20, 18)
        self.personality_preview.setAccessibleName("Selected personality instructions")
        selection.content.addWidget(self.personality_preview)
        self.attitude_combo.currentIndexChanged.connect(self._update_personality_preview)
        personality_layout.addWidget(selection)
        personality_layout.addWidget(instructions)
        self.attitudes = _AttitudesPage(settings)
        personality_layout.addWidget(self.attitudes)
        self.tabs = SettingsTabs(
            [("Voice setup", self.voice), ("Personality & instructions", personality)]
        )
        self.tabs.current_changed.connect(self._on_tab_changed)
        self.attitudes.changed.connect(self._refresh_attitudes)
        layout.addWidget(self.tabs)
        layout.addLayout(links)
        layout.addStretch()
        self._refresh_attitudes()

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            self.voice.refresh_vc_model_combos()

    def _refresh_attitudes(self) -> None:
        target = (
            self.attitude_combo.currentText()
            if self.attitude_combo.count()
            else self._saved_attitude
        )
        self.attitude_combo.clear()
        self.attitude_combo.addItem("None", "")
        for name in self.attitudes.all_attitude_names():
            self.attitude_combo.addItem(name, name)
        self.attitude_combo.setCurrentIndex(max(0, self.attitude_combo.findData(target)))
        self._update_personality_preview()

    def _update_personality_preview(self) -> None:
        name = self.attitude_combo.currentData() or ""
        self.personality_preview.setText(
            self.attitudes.personality_text(name) if name else "Only your base instructions apply."
        )

    def refresh(self) -> None:
        self.voice.refresh_vc_model_combos()
        self._refresh_attitudes()

    def get_settings(self) -> dict:
        return {
            **self.voice.get_settings(),
            **self.attitudes.get_settings(),
            "system_prompt": self.prompt.toPlainText().strip(),
            "selected_attitude": self.attitude_combo.currentData() or "",
        }
