"""Wake phrase setup, local prerequisites and quiet-conversation preferences."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QSpinBox, QVBoxLayout, QWidget

from roomkit_ui.features import unavailable_reason
from roomkit_ui.model_catalog import (
    is_vad_model_downloaded,
    is_wakeword_encoder_downloaded,
    vad_model_path,
    wakeword_encoder_path,
)
from roomkit_ui.wakeword import clear as clear_fingerprint
from roomkit_ui.wakeword import load as load_fingerprint
from roomkit_ui.widgets.install_offer import InstallOffer
from roomkit_ui.widgets.settings.controls import (
    AdvancedSection,
    FeedbackLabel,
    SettingsSection,
    SettingsToggle,
    StatusBadge,
    label,
    navigation_link,
    page_layout,
)
from roomkit_ui.widgets.settings.model_jobs import model_downloads
from roomkit_ui.widgets.settings.model_library import model_groups, wakeword_encoder_model
from roomkit_ui.widgets.settings.models_widgets import _ModelRow

_VAD_MODEL = "ten-vad"
_VAD_FILE = "ten-vad.int8.onnx"
_SENSITIVITY = (
    ("Cautious", "cautious", "Fewer accidental activations; you may need to repeat the phrase."),
    ("Balanced", "balanced", "A balance between recognition and accidental activations."),
    (
        "Responsive",
        "responsive",
        "Recognizes more variations; similar sounds may also activate it.",
    ),
)


class _WakeWordPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = dict(settings)
        self._runner = model_downloads()
        layout = page_layout(
            self,
            "Wake Word",
            "Start a conversation with a phrase you record. Detection runs on this device.",
        )
        activation = SettingsSection("Hands-free activation")
        self._enabled = SettingsToggle(
            "Listen for the wake word", bool(settings.get("wakeword_enabled", False))
        )
        activation.add_row(
            "Listen for the wake word",
            "Listening resumes after Settings closes. "
            "It pauses during conversations and dictation.",
            self._enabled,
        )
        self._sensitivity = QComboBox()
        for title, value, _description in _SENSITIVITY:
            self._sensitivity.addItem(title, value)
        index = self._sensitivity.findData(settings.get("wakeword_sensitivity", "balanced"))
        self._sensitivity.setCurrentIndex(index if index >= 0 else 1)
        activation.add_row(
            "Sensitivity", "How closely speech must match your phrase.", self._sensitivity
        )
        self._sensitivity_hint = label("", "settingsHint")
        self._sensitivity_hint.setContentsMargins(18, 0, 18, 16)
        activation.content.addWidget(self._sensitivity_hint)
        self._sensitivity.currentIndexChanged.connect(self._update_sensitivity)
        self._update_sensitivity()
        layout.addWidget(activation)

        phrase = SettingsSection("Your wake phrase")
        phrase.content.setContentsMargins(18, 16, 18, 16)
        phrase.content.setSpacing(12)
        self._badge = StatusBadge()
        phrase.content.addWidget(self._badge, 0, Qt.AlignLeft)
        self._status = FeedbackLabel()
        phrase.content.addWidget(self._status)
        self._phrase_info = label("", "settingsHint")
        self._phrase_info.setTextFormat(Qt.PlainText)
        phrase.content.addWidget(self._phrase_info)
        buttons = QHBoxLayout()
        self._setup_button = QPushButton("Record a phrase…")
        self._setup_button.setAutoDefault(False)
        self._setup_button.clicked.connect(self._open_wizard)
        buttons.addWidget(self._setup_button)
        self._forget_button = QPushButton("Forget phrase")
        self._forget_button.setAutoDefault(False)
        self._forget_button.clicked.connect(self._forget)
        buttons.addWidget(self._forget_button)
        buttons.addStretch()
        phrase.content.addLayout(buttons)
        phrase.content.addWidget(
            label("Recording or forgetting a phrase updates it immediately.", "settingsHint")
        )
        layout.addWidget(phrase)

        requirements = QWidget()
        required_layout = QVBoxLayout(requirements)
        required_layout.setContentsMargins(0, 0, 0, 0)
        required_layout.setSpacing(12)
        self.component_offer = InstallOffer("wakeword")
        self.component_offer.installed.connect(self.refresh)
        required_layout.addWidget(self.component_offer)
        self._encoder_row = _ModelRow(wakeword_encoder_model(), allow_delete=False)
        vad = next(
            model for group in model_groups() for model in group.models if model.id == _VAD_MODEL
        )
        self._vad_row = _ModelRow(vad, allow_delete=False)
        self._download_rows = (self._encoder_row, self._vad_row)
        for row in self._download_rows:
            row.action_btn.clicked.connect(
                lambda _checked=False, model=row.model: self._runner.start(model)
            )
            required_layout.addWidget(row)
        self.models_link = navigation_link("Manage files in Models & components →")
        self.models_link.clicked.connect(lambda: self.navigate_requested.emit("models"))
        required_layout.addWidget(self.models_link, 0, Qt.AlignLeft)
        self.requirements = AdvancedSection("Components & local models", requirements)
        self.requirements.set_expanded(bool(self._blocker()))
        layout.addWidget(self.requirements)

        hangup = SettingsSection(
            "End quiet conversations",
            "Applies to every conversation, including those started manually.",
        )
        self._hangup_enabled = SettingsToggle(
            "Automatic hangup", bool(settings.get("idle_hangup_enabled", False))
        )
        hangup.add_row(
            "Automatic hangup",
            "End a quiet session when neither the assistant nor a tool is working.",
            self._hangup_enabled,
        )
        self._hangup_seconds = QSpinBox()
        self._hangup_seconds.setRange(5, 300)
        self._hangup_seconds.setSuffix(" s")
        self._hangup_seconds.setValue(int(settings.get("idle_hangup_seconds", 15) or 15))
        self._hangup_seconds.setEnabled(self._hangup_enabled.isChecked())
        self._hangup_enabled.toggled.connect(self._hangup_seconds.setEnabled)
        hangup.add_row(
            "Quiet period", "Wait this long before ending the session.", self._hangup_seconds
        )
        layout.addWidget(hangup)
        layout.addStretch()
        self._enabled.toggled.connect(self.refresh)
        self._runner.changed.connect(self._download_changed)
        self.refresh()

    def set_capture_settings(self, settings: dict) -> None:
        """Use pending audio/provider choices when the user opens the recording wizard."""
        self._settings.update(settings)

    def _blocker(self) -> str | None:
        reason = unavailable_reason("wakeword")
        if reason:
            return reason
        if not is_vad_model_downloaded(_VAD_MODEL):
            return "Download TEN VAD in Components & local models below before recording a phrase."
        if not is_wakeword_encoder_downloaded():
            return "Download the wake-word encoder below before recording a phrase."
        return None

    @Slot()
    def refresh(self) -> None:
        blocker = self._blocker()
        fingerprint = load_fingerprint()
        enrolled = fingerprint is not None and fingerprint.usable
        self._setup_button.setEnabled(blocker is None)
        self._setup_button.setText("Record again…" if enrolled else "Record a phrase…")
        # A missing file must not erase the stored choice, or prevent switching it off.
        self._enabled.setEnabled((not blocker and enrolled) or self._enabled.isChecked())
        self._forget_button.setEnabled(fingerprint is not None)
        self._phrase_info.setText(
            f"{len(fingerprint.prototypes)} phrase recordings · "
            f"{len(fingerprint.decoys)} comparison recordings"
            if fingerprint is not None and enrolled
            else "Record your phrase and similar sounds in the guided setup."
        )
        states = [self._runner.states.get(row.model.id) for row in self._download_rows]
        error = next((state.error for state in states if state and state.phase == "error"), "")
        active = any(state and state.phase in {"resolving", "downloading"} for state in states)
        if error:
            self._badge.set_status("Download failed", "error")
            self._status.set_status(f"Download failed: {error}", "error")
        elif active:
            self._badge.set_status("Downloading", "active")
            self._status.set_status(
                "Downloading required files. Progress continues if you close Settings."
            )
        elif blocker:
            self._badge.set_status("Setup required", "neutral")
            self._status.set_status(blocker)
        elif enrolled:
            assert fingerprint is not None
            self._badge.set_status("Phrase recorded", "success")
            self._status.set_status(f"Enrolled: “{fingerprint.label}”")
        else:
            self._badge.set_status("No phrase recorded", "neutral")
            self._status.set_status(
                "The required files are available. Record a phrase to enable listening."
            )
        for row in self._download_rows:
            row.refresh(self._runner.states.get(row.model.id))
        self.component_offer.set_feature("wakeword")

    @Slot(str)
    def _download_changed(self, model_id: str) -> None:
        if any(row.model.id == model_id for row in self._download_rows):
            self.refresh()

    def _update_sensitivity(self) -> None:
        self._sensitivity_hint.setText(_SENSITIVITY[self._sensitivity.currentIndex()][2])

    def _open_wizard(self) -> None:
        from roomkit_ui.wakeword.controller import capture_rate
        from roomkit_ui.widgets.wakeword_wizard import WakeWordWizard

        dialog = WakeWordWizard(
            str(wakeword_encoder_path()),
            str(vad_model_path(_VAD_MODEL) / _VAD_FILE),
            input_device=self._settings.get("input_device"),
            capture_rate=capture_rate(self._settings),
            parent=self,
        )
        if dialog.exec():
            self._enabled.setChecked(True)
            self._hangup_enabled.setChecked(True)
        self.refresh()

    def _forget(self) -> None:
        clear_fingerprint()
        self._enabled.setChecked(False)
        self.refresh()

    def get_settings(self) -> dict:
        return {
            "wakeword_enabled": self._enabled.isChecked(),
            "wakeword_sensitivity": self._sensitivity.currentData(),
            "idle_hangup_enabled": self._hangup_enabled.isChecked(),
            "idle_hangup_seconds": self._hangup_seconds.value(),
        }
