"""One destination for recorded audio, pipeline capture and trace export."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from roomkit_ui.widgets.settings.audio_capture_page import AudioCapturePage
from roomkit_ui.widgets.settings.controls import SettingsTabs, page_layout
from roomkit_ui.widgets.settings.recordings_page import RecordingsPage
from roomkit_ui.widgets.settings.telemetry_page import _TelemetryPage


class DiagnosticsPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = page_layout(
            self,
            "Diagnostics",
            "Explore recorded audio and collect the details you need to investigate a session.",
        )
        self.recordings = RecordingsPage(settings)
        self.capture = AudioCapturePage(settings)
        self.telemetry = _TelemetryPage(settings)
        self.tabs = SettingsTabs(
            [
                ("Recorded audio", self.recordings),
                ("Pipeline capture", self.capture),
                ("Telemetry", self.telemetry),
            ]
        )
        layout.addWidget(self.tabs)
        layout.addStretch()
        self.recordings.navigate_requested.connect(self.navigate_requested)
        self.capture.directory_changed.connect(self.recordings.set_debug_directory)
        self.tabs.current_changed.connect(self._tab_changed)

    def _tab_changed(self, index: int) -> None:
        if index == 0:
            self.recordings.refresh_files()
        elif index == 2:
            self.telemetry.refresh()

    def refresh(self) -> None:
        self._tab_changed(self.tabs.bar.currentIndex())

    def reveal_search_target(self) -> None:
        if self.tabs.bar.currentIndex() == 0:
            self.recordings.search.clear()
            self.recordings.source.setCurrentIndex(0)
            self.recordings.refresh_files()

    def set_recording_directory(self, directory: str) -> None:
        self.recordings.set_recording_directory(directory)

    def get_settings(self) -> dict:
        return {**self.capture.get_settings(), **self.telemetry.get_settings()}
