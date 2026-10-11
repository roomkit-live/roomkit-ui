"""Wake word settings: enrol a phrase, tune sensitivity, auto-hangup."""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.features import unavailable_reason
from roomkit_ui.model_catalog import (
    WAKEWORD_ENCODER_SIZE,
    is_vad_model_downloaded,
    is_wakeword_encoder_downloaded,
    vad_model_path,
    wakeword_encoder_path,
)
from roomkit_ui.theme import colors
from roomkit_ui.wakeword import clear as clear_fingerprint
from roomkit_ui.wakeword import load as load_fingerprint

logger = logging.getLogger(__name__)

_VAD_MODEL = "ten-vad"
_VAD_FILE = "ten-vad.int8.onnx"

# The factors live in wakeword.page_sensitivity.FACTORS.
_SENSITIVITY_LABELS = [
    ("Cautious — rarely wrong, may need repeating", "cautious"),
    ("Balanced", "balanced"),
    ("Responsive — always answers, may misfire", "responsive"),
]


class _WakeWordPage(QWidget):
    """Enrol and arm a spoken wake word."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("Wake Word")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel(
            "Listen locally for a spoken phrase and open a session when it is "
            "heard. Nothing leaves the machine until it fires."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {self._c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        # -- enrolment --
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"QLabel {{ font-size: 12px; color: {self._c['TEXT_PRIMARY']};"
            f" background: {self._c['BG_TERTIARY']}; border-radius: 6px;"
            f" padding: 10px 12px; }}"
        )
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._download_button = QPushButton()
        self._download_button.clicked.connect(self._download_encoder)
        self._download_task: asyncio.Task | None = None
        buttons.addWidget(self._download_button)
        self._setup_button = QPushButton("Set up wake word…")
        self._setup_button.clicked.connect(self._open_wizard)
        buttons.addWidget(self._setup_button)
        self._forget_button = QPushButton("Forget phrase")
        self._forget_button.clicked.connect(self._forget)
        buttons.addWidget(self._forget_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        # -- options --
        form = QFormLayout()
        form.setSpacing(10)

        self._enabled = QCheckBox("Listen for the wake word")
        self._enabled.setChecked(bool(settings.get("wakeword_enabled", False)))
        form.addRow("", self._enabled)

        self._sensitivity = QComboBox()
        for label, value in _SENSITIVITY_LABELS:
            self._sensitivity.addItem(label, value)
        current = str(settings.get("wakeword_sensitivity", "balanced"))
        index = self._sensitivity.findData(current)
        self._sensitivity.setCurrentIndex(index if index >= 0 else 1)
        form.addRow("Sensitivity", self._sensitivity)

        self._hangup_enabled = QCheckBox("Hang up when the conversation goes quiet")
        self._hangup_enabled.setChecked(bool(settings.get("idle_hangup_enabled", False)))
        form.addRow("", self._hangup_enabled)

        self._hangup_seconds = QSpinBox()
        self._hangup_seconds.setRange(5, 300)
        self._hangup_seconds.setSuffix(" s")
        self._hangup_seconds.setValue(int(settings.get("idle_hangup_seconds", 15) or 15))
        form.addRow("After", self._hangup_seconds)

        layout.addLayout(form)
        layout.addStretch(1)

        self.refresh()

    # -- state ---------------------------------------------------------------

    def _blocker(self) -> str | None:
        """What stops the wake word from working, phrased for the user."""
        reason = unavailable_reason("wakeword")
        if reason:
            return reason
        if not is_vad_model_downloaded(_VAD_MODEL):
            return "The TEN VAD model is missing — download it in AI Models."
        if not is_wakeword_encoder_downloaded():
            return "The wake-word encoder is not downloaded yet."
        return None

    def refresh(self) -> None:
        """Re-read what is enrolled and what is missing."""
        blocker = self._blocker()
        fingerprint = load_fingerprint()

        if blocker:
            self._status.setText(blocker)
            self._setup_button.setEnabled(False)
            self._enabled.setEnabled(False)
        elif fingerprint is not None and fingerprint.usable:
            self._status.setText(
                f"Enrolled: “{fingerprint.label}” — "
                f"{len(fingerprint.prototypes)} recordings, "
                f"{len(fingerprint.decoys)} decoys."
            )
            self._setup_button.setEnabled(True)
            self._setup_button.setText("Record again…")
            self._enabled.setEnabled(True)
        else:
            self._status.setText("No phrase enrolled yet.")
            self._setup_button.setEnabled(True)
            self._enabled.setEnabled(False)
            self._enabled.setChecked(False)

        self._forget_button.setEnabled(fingerprint is not None)
        self._refresh_download_button()

    def _refresh_download_button(self) -> None:
        """Offer the encoder download whenever it is what's missing."""
        missing = not unavailable_reason("wakeword") and not is_wakeword_encoder_downloaded()
        self._download_button.setVisible(missing)
        if self._download_task is None:
            self._download_button.setEnabled(True)
            self._download_button.setText(f"Download encoder ({WAKEWORD_ENCODER_SIZE})")

    # -- actions -------------------------------------------------------------

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
            # Enrolling is the user asking for this; arming it is the point.
            self._enabled.setEnabled(True)
            self._enabled.setChecked(True)
            self._hangup_enabled.setChecked(True)
        self.refresh()

    def _download_encoder(self) -> None:
        from roomkit_ui.wakeword.encoder_download import download_encoder

        loop = asyncio.get_event_loop()
        self._download_button.setEnabled(False)
        self._show_download_progress(0)

        def progress(done: int, total: int) -> None:
            pct = min(done * 100 // total, 100) if total > 0 else 0
            loop.call_soon_threadsafe(self._show_download_progress, pct)

        async def run() -> None:
            try:
                await download_encoder(progress)
            except Exception as exc:
                logger.exception("Wake-word encoder download failed")
                self._finish_download(f"Download failed: {exc}")
            else:
                self._finish_download(None)

        self._download_task = loop.create_task(run())

    def _show_download_progress(self, pct: int) -> None:
        try:
            self._download_button.setText(f"Downloading… {pct}%")
        except RuntimeError:
            pass  # the dialog closed while the download ran

    def _finish_download(self, error: str | None) -> None:
        self._download_task = None
        try:
            self.refresh()
            if error:
                self._status.setText(error)
                self._download_button.setText("Retry download")
        except RuntimeError:
            pass  # the dialog closed while the download ran

    def _forget(self) -> None:
        clear_fingerprint()
        self._enabled.setChecked(False)
        self.refresh()

    # -- persistence ---------------------------------------------------------

    def get_settings(self) -> dict:
        return {
            "wakeword_enabled": self._enabled.isChecked(),
            "wakeword_sensitivity": self._sensitivity.currentData(),
            "idle_hangup_enabled": self._hangup_enabled.isChecked(),
            "idle_hangup_seconds": self._hangup_seconds.value(),
        }
