"""Pipeline capture settings; session recording belongs to Privacy."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.paths import data_dir
from roomkit_ui.widgets.settings.controls import (
    FeedbackLabel,
    SettingsForm,
    SettingsSection,
    SettingsToggle,
    label,
)

STAGES = [
    ("transport_raw", "Transport input · before echo cancellation"),
    ("raw", "Pipeline input"),
    ("post_aec", "After echo cancellation"),
    ("post_agc", "After gain control"),
    ("post_denoiser", "After noise reduction"),
    ("post_vad_speech", "Detected speech segments"),
    ("outbound_raw", "Output · before processing"),
    ("outbound_final", "Output · after processing"),
    ("aec_reference", "Echo cancellation reference"),
]


class AudioCapturePage(QWidget):
    directory_changed = Signal(str)

    def __init__(self, settings: dict) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        capture = SettingsSection(
            "Pipeline capture",
            "Compare audio before and after processing to investigate voice issues.",
        )
        self.enabled = SettingsToggle(
            "Capture pipeline audio", settings.get("debug_taps_enabled", False)
        )
        capture.add_row(
            "Capture pipeline audio",
            "Writes unencrypted WAV files from the next session. "
            "Turn off when finished debugging.",
            self.enabled,
        )
        layout.addWidget(capture)
        options = SettingsSection(
            "Capture options", "Only stages used by the active audio pipeline produce files."
        )
        options.content.setContentsMargins(18, 16, 18, 16)
        form = SettingsForm()
        self.stages = QComboBox()
        self.stages.addItems(["All stages", "Selected stages"])
        saved = [
            s.strip() for s in settings.get("debug_taps_stages", "all").split(",") if s.strip()
        ]
        all_stages = "all" in saved
        self.stages.setCurrentIndex(0 if all_stages else 1)
        form.addRow("Stages to capture", self.stages)
        self.stage_fields = QWidget()
        checks = QVBoxLayout(self.stage_fields)
        checks.setContentsMargins(0, 0, 0, 0)
        self.stage_checks = {}
        # Retain stages saved by a newer RoomKit version instead of silently dropping them.
        entries = [*STAGES, *((s, s) for s in saved if s != "all" and s not in dict(STAGES))]
        for key, title in entries:
            check = QCheckBox(title)
            check.setChecked(all_stages or key in saved)
            check.toggled.connect(self._update_stages)
            self.stage_checks[key] = check
            checks.addWidget(check)
        form.addWidget(self.stage_fields)
        self.feedback = FeedbackLabel()
        form.addWidget(self.feedback)
        directory_row = QWidget()
        directory_layout = QHBoxLayout(directory_row)
        directory_layout.setContentsMargins(0, 0, 0, 0)
        self.directory = QLineEdit(settings.get("debug_output_dir", ""))
        self.directory.setPlaceholderText(str(data_dir() / "debug_audio"))
        self.directory.setAccessibleName("Pipeline capture folder")
        self.directory.setProperty("settingsFormField", True)
        directory_layout.addWidget(self.directory, 1)
        browse = QPushButton("Browse…")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        directory_layout.addWidget(browse)
        form.addRow("Capture folder", directory_row)
        form.addWidget(
            label(
                "Leave blank to use the default folder. Files stay on disk until you delete them.",
                "settingsHint",
            )
        )
        options.content.addLayout(form)
        layout.addWidget(options)
        self.stages.currentIndexChanged.connect(self._update_stages)
        self.directory.textChanged.connect(self.directory_changed)
        self._update_stages()

    def _update_stages(self) -> None:
        custom = self.stages.currentIndex() == 1
        self.stage_fields.setVisible(custom)
        empty = custom and not any(check.isChecked() for check in self.stage_checks.values())
        if empty:
            # RoomKit interprets an empty list as ALL stages, so disable capture explicitly.
            self.enabled.setChecked(False)
        self.enabled.setEnabled(not empty)
        self.feedback.set_status(
            "Capture is off. Select at least one stage to enable it again." if empty else ""
        )

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Pipeline capture folder",
            self.directory.text().strip() or self.directory.placeholderText(),
        )
        if directory:
            self.directory.setText(directory)

    def get_settings(self) -> dict:
        stages = (
            "all"
            if self.stages.currentIndex() == 0
            else ",".join(key for key, check in self.stage_checks.items() if check.isChecked())
        )
        return {
            "debug_taps_enabled": self.enabled.isChecked(),
            "debug_taps_stages": stages,
            "debug_output_dir": self.directory.text().strip(),
        }
