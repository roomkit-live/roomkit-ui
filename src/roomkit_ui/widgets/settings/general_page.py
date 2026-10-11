"""Everyday preferences with reusable native Settings sections."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from roomkit_ui.widgets.hotkey_button import HotkeyButton
from roomkit_ui.widgets.settings.appearance import ThemePicker
from roomkit_ui.widgets.settings.controls import (
    SettingsSection,
    SettingsToggle,
    label,
    navigation_link,
    page_layout,
)


class _GeneralPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = page_layout(self, "General", "Appearance, shortcuts, and everyday preferences.")
        layout.addWidget(self._appearance(settings))
        layout.addWidget(self._shortcuts(settings))
        personal = SettingsSection("Make it yours")
        self.personality_link = navigation_link("Choose personality →")
        self.personality_link.clicked.connect(
            lambda: self.navigate_requested.emit("conversation:personality")
        )
        personal.add_row(
            "Your assistant's personality",
            "Choose a communication style and instructions.",
            self.personality_link,
        )
        self.memory_link = navigation_link("Manage memory →")
        self.memory_link.clicked.connect(lambda: self.navigate_requested.emit("privacy"))
        personal.add_row(
            "Conversation memory",
            "Choose what your assistant remembers between sessions.",
            self.memory_link,
        )
        layout.addWidget(personal)
        self.audio_link = navigation_link("Configure audio & voice →")
        self.audio_link.clicked.connect(lambda: self.navigate_requested.emit("audio"))
        audio = SettingsSection("Your audio setup")
        audio.add_row(
            "Microphone and speakers",
            "Choose your devices and adjust audio quality.",
            self.audio_link,
        )
        layout.addWidget(audio)
        layout.addStretch()

    def _appearance(self, settings: dict) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(label("Appearance", "settingsSectionTitle"))
        layout.addWidget(label("A comfortable space, day or night.", "settingsHint"))
        self.theme_picker = ThemePicker(settings.get("theme", "dark"))
        layout.addWidget(self.theme_picker)
        layout.addWidget(label("Your theme changes immediately.", "settingsHint"))
        return section

    def _shortcuts(self, settings: dict) -> SettingsSection:
        section = SettingsSection("Keyboard shortcuts", "One gesture to start a conversation.")
        self.assistant_hotkey_enabled = SettingsToggle(
            "Enable assistant shortcut", bool(settings.get("assistant_hotkey_enabled", True))
        )
        section.add_row(
            "Talk to your assistant",
            "Start or end a voice session from any app.",
            self.assistant_hotkey_enabled,
        )
        self.assistant_hotkey = HotkeyButton()
        self.assistant_hotkey.setAutoDefault(False)
        self.assistant_hotkey.setMinimumWidth(140)
        self.assistant_hotkey.set_value(settings.get("assistant_hotkey", "<ctrl>+<shift>+a"))
        self.assistant_hotkey.setEnabled(self.assistant_hotkey_enabled.isChecked())
        self.assistant_hotkey_enabled.toggled.connect(self.assistant_hotkey.setEnabled)
        section.add_row(
            "Assistant shortcut",
            "Click the keys, then press your new shortcut. Escape cancels recording.",
            self.assistant_hotkey,
        )
        self.dictation_link = navigation_link("Configure dictation →")
        self.dictation_link.clicked.connect(lambda: self.navigate_requested.emit("dictation"))
        section.add_row(
            "Dictation",
            "Speak directly into the app you are using.",
            self.dictation_link,
        )
        return section

    def get_settings(self) -> dict:
        return {
            "theme": self.theme_picker.value(),
            "assistant_hotkey_enabled": self.assistant_hotkey_enabled.isChecked(),
            "assistant_hotkey": self.assistant_hotkey.value(),
        }
