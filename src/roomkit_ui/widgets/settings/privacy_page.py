"""Conversation history and session recording preferences."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QPushButton, QWidget

from roomkit_ui.memory import conversations_db_path
from roomkit_ui.paths import data_dir
from roomkit_ui.widgets.settings.controls import (
    SettingsForm,
    SettingsSection,
    SettingsToggle,
    label,
    navigation_link,
    page_layout,
)


class PrivacyPage(QWidget):
    navigate_requested = Signal(str)
    recording_directory_changed = Signal(str)

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = page_layout(
            self, "Privacy & memory", "Control what stays on this device after a conversation."
        )
        boundary = SettingsSection("On this device and in the cloud")
        boundary.content.setContentsMargins(20, 18, 20, 18)
        boundary.content.addWidget(
            label(
                "History and saved audio stay on this device. Cloud providers receive the audio "
                "or text needed for the features you use. Turning local memory or recording off "
                "does not change your providers' data policies.",
                "settingsHint",
            )
        )
        layout.addWidget(boundary)
        memory = SettingsSection("Conversation memory")
        self.conversation_memory = SettingsToggle(
            "Remember conversations", bool(settings.get("conversation_memory", True))
        )
        memory.add_row(
            "Remember conversations",
            "Keep local history so your assistant can recall previous sessions.",
            self.conversation_memory,
        )
        hint = label(
            "Turning memory off affects future sessions. Existing history remains on this device.",
            "settingsHint",
        )
        hint.setContentsMargins(18, 0, 18, 0)
        memory.content.addWidget(hint)
        location_form = SettingsForm()
        location_form.setContentsMargins(20, 12, 20, 18)
        location = QLineEdit(str(conversations_db_path()))
        location.setReadOnly(True)
        location.setAccessibleName("Local history database")
        location.setToolTip(location.text())
        location_form.addRow("Local history database", location)
        memory.content.addLayout(location_form)
        layout.addWidget(memory)

        recording = SettingsSection(
            "Session recordings", "Changes take effect on the next session."
        )
        self.recording_enabled = SettingsToggle(
            "Record session audio", bool(settings.get("recording_enabled", False))
        )
        recording.add_row(
            "Record session audio",
            "Save full session audio as plain, unencrypted WAV files.",
            self.recording_enabled,
        )
        self.mode = QComboBox()
        for title, value in [
            ("Microphone and assistant", "both"),
            ("Microphone only", "inbound_only"),
            ("Assistant only", "outbound_only"),
        ]:
            self.mode.addItem(title, value)
        self.mode.setCurrentIndex(
            max(0, self.mode.findData(settings.get("recording_mode", "both")))
        )
        recording.add_row(
            "Audio to record", "Choose which side of the conversation to keep.", self.mode
        )
        self.channels = QComboBox()
        for title, value in [
            ("Stereo · mic left, assistant right", "stereo"),
            ("Separate files", "separate"),
            ("Mixed", "mixed"),
        ]:
            self.channels.addItem(title, value)
        self.channels.setCurrentIndex(
            max(0, self.channels.findData(settings.get("recording_channels", "stereo")))
        )
        recording.add_row("File layout", "Organize the recorded audio channels.", self.channels)
        destination = QWidget()
        destination.setObjectName("settingsRow")
        row = QHBoxLayout(destination)
        row.setContentsMargins(18, 12, 18, 16)
        self.output_dir = QLineEdit(settings.get("recording_output_dir", ""))
        self.output_dir.setPlaceholderText(str(data_dir() / "recordings"))
        self.output_dir.setAccessibleName("Recording output folder")
        self.output_dir.textChanged.connect(self.recording_directory_changed)
        row.addWidget(self.output_dir, 1)
        browse = QPushButton("Browse…")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        recording.content.addWidget(destination)
        self._recording_controls = (self.mode, self.channels, destination)
        self.recording_enabled.toggled.connect(self._update_recording)
        self._update_recording(self.recording_enabled.isChecked())
        layout.addWidget(recording)
        self.files_link = navigation_link("View recordings & audio diagnostics →")
        self.files_link.clicked.connect(lambda: self.navigate_requested.emit("diagnostics"))
        layout.addWidget(self.files_link, 0, Qt.AlignLeft)
        self.providers_link = navigation_link("Review providers & keys →")
        self.providers_link.clicked.connect(lambda: self.navigate_requested.emit("providers"))
        self.telemetry_link = navigation_link("Review telemetry export →")
        self.telemetry_link.clicked.connect(
            lambda: self.navigate_requested.emit("diagnostics:telemetry")
        )
        layout.addWidget(self.providers_link, 0, Qt.AlignLeft)
        layout.addWidget(self.telemetry_link, 0, Qt.AlignLeft)
        layout.addStretch()

    def _update_recording(self, enabled: bool) -> None:
        for control in self._recording_controls:
            control.setEnabled(enabled)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Recording output folder", self.output_dir.text()
        )
        if folder:
            self.output_dir.setText(folder)

    def get_settings(self) -> dict:
        return {
            "conversation_memory": self.conversation_memory.isChecked(),
            "recording_enabled": self.recording_enabled.isChecked(),
            "recording_mode": self.mode.currentData(),
            "recording_channels": self.channels.currentData(),
            "recording_output_dir": self.output_dir.text().strip(),
        }
