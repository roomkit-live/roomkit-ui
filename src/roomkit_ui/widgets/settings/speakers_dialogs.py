"""Dialog and row widgets for the Speakers settings page."""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from roomkit_ui.widgets.settings.controls import (
    FeedbackLabel,
    SettingsForm,
    SettingsSection,
    StatusBadge,
    label,
)
from roomkit_ui.widgets.settings.style import settings_stylesheet

logger = logging.getLogger(__name__)


class _EnrollDialog(QDialog):
    """Dialog for enrolling a new speaker via a 10-second recording."""

    def __init__(self, model_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Enroll speaker")
        self.setObjectName("settingsPanel")
        self.setStyleSheet(settings_stylesheet(str(QSettings().value("room/theme", "dark"))))
        self.setMinimumSize(440, 480)
        self.resize(520, 560)
        self.setModal(True)
        self._model_path = model_path
        self.result_name: str = ""
        self.result_embeddings: list[list[float]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("Enroll speaker", "settingsSectionTitle"))
        layout.addWidget(
            label(
                "Enter a name, then read the text aloud during the 10-second recording.",
                "settingsHint",
            )
        )
        form = SettingsForm()
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Speaker name")
        form.addRow("Name", self._name_input)
        layout.addLayout(form)
        prompt = SettingsSection("Read aloud")
        prompt.content.setContentsMargins(20, 18, 20, 18)
        self._prompt_label = label("", "settingsDescription")
        self._set_prompt("en")
        prompt.content.addWidget(self._prompt_label)
        layout.addWidget(prompt)
        languages = QHBoxLayout()
        languages.addWidget(label("Prompt language", "settingsHint"))
        for lang, title in (("en", "English"), ("fr", "Français")):
            button = QPushButton(title)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _=False, lg=lang: self._set_prompt(lg))
            languages.addWidget(button)
        languages.addStretch()
        layout.addLayout(languages)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setAccessibleName("Voice recording progress")
        self._progress.hide()
        layout.addWidget(self._progress)
        self._status = FeedbackLabel()
        layout.addWidget(self._status)
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self._record_btn = QPushButton("Record · 10s")
        self._record_btn.setAutoDefault(False)
        self._record_btn.clicked.connect(self._start_recording)
        actions.addWidget(self._record_btn)
        layout.addLayout(actions)

    _PROMPTS = {
        "en": (
            "\u201cThe rainbow is a division of white light into many beautiful colors. "
            "These take the shape of a long round arch, with its path high above, "
            "and its two ends apparently beyond the horizon.\u201d"
        ),
        "fr": (
            "\u00ab L\u2019arc-en-ciel est une division de la lumi\u00e8re blanche "
            "en de nombreuses couleurs magnifiques. Il prend la forme d\u2019un long "
            "arc arrondi, dont le sommet s\u2019\u00e9l\u00e8ve haut dans le ciel et "
            "dont les deux extr\u00e9mit\u00e9s semblent d\u00e9passer l\u2019horizon. \u00bb"
        ),
    }

    def _set_prompt(self, lang: str) -> None:
        self._prompt_label.setText(self._PROMPTS.get(lang, self._PROMPTS["en"]))

    def _start_recording(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            self._status.set_status("Please enter a name.", "error")
            return

        self._record_btn.setEnabled(False)
        self._name_input.setEnabled(False)
        self._progress.show()
        self._progress.setValue(0)
        self._status.set_status("Recording… speak now!")

        loop = asyncio.get_event_loop()

        def _progress(pct: float) -> None:
            loop.call_soon_threadsafe(self._show_progress, pct)

        async def _run() -> None:
            try:
                from roomkit_ui.enrollment import record_and_extract_multi

                embeddings = await record_and_extract_multi(
                    self._model_path, duration=10.0, progress=_progress
                )
                if not isValid(self):
                    return  # the Settings dialog closed during the recording
                self.result_name = name
                self.result_embeddings = embeddings
                n = len(embeddings)
                self._status.set_status(
                    f"Done! Extracted {n} voice sample{'s' if n != 1 else ''}.", "success"
                )
                QTimer.singleShot(500, self.accept)
            except Exception as e:
                logger.exception("Enrollment failed")
                if not isValid(self):
                    return
                self._status.set_status(f"Error: {e}", "error")
                self._record_btn.setEnabled(True)
                self._name_input.setEnabled(True)

        loop.create_task(_run())

    def _show_progress(self, pct: float) -> None:
        if isValid(self):  # the recording thread outlives a closed dialog
            self._progress.setValue(int(pct * 100))


class _SpeakerRow(QWidget):
    """A row for a single enrolled speaker."""

    def __init__(
        self,
        name: str,
        sample_count: int,
        is_primary: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.speaker_name = name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        name_label = label(name, "settingsRowTitle")
        name_label.setTextFormat(Qt.PlainText)
        heading.addWidget(name_label, 1)
        self._primary_badge = StatusBadge()
        self._primary_badge.set_status("Primary", "active")
        self._primary_badge.setVisible(is_primary)
        heading.addWidget(self._primary_badge)
        layout.addLayout(heading)
        layout.addWidget(
            label(f"{sample_count} voice sample{'s' if sample_count != 1 else ''}", "settingsHint")
        )
        actions = QHBoxLayout()
        self.primary_btn = QPushButton("Set primary")
        self.primary_btn.setVisible(not is_primary)
        self.sample_btn = QPushButton("Add sample")
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("settingsDanger")
        for button in (self.primary_btn, self.sample_btn, self.delete_btn):
            button.setAutoDefault(False)
            button.setAccessibleName(f"{button.text()} · {name}")
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
