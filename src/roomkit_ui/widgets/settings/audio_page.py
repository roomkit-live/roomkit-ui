"""Audio devices, processing and speaker identification."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget

from roomkit_ui.widgets.settings.audio_processing import AudioSettings, _list_audio_devices
from roomkit_ui.widgets.settings.controls import SettingsTabs, navigation_link, page_layout
from roomkit_ui.widgets.settings.speakers_page import _SpeakersPage


class AudioPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = page_layout(
            self, "Audio & voice", "Your devices, audio quality and speaker recognition."
        )
        self.models_link = navigation_link("Browse local models →")
        self.models_link.clicked.connect(lambda: self.navigate_requested.emit("models"))
        self.processing = AudioSettings(settings, _list_audio_devices())
        self.speakers = _SpeakersPage(settings)
        self.tabs = SettingsTabs(
            [
                ("Devices & processing", self.processing),
                ("Speaker recognition", self.speakers),
            ]
        )
        layout.addWidget(self.tabs)
        layout.addWidget(self.models_link, 0, Qt.AlignLeft)
        layout.addStretch()

    def refresh(self) -> None:
        self.processing.refresh_models()
        self.speakers.refresh_models()

    def get_settings(self) -> dict:
        return {**self.processing.get_settings(), **self.speakers.get_settings()}
