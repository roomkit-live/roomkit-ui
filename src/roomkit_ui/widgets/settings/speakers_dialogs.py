"""Dialog and row widgets for the Speakers settings page."""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors

logger = logging.getLogger(__name__)


class _EnrollDialog(QDialog):
    """Dialog for enrolling a new speaker via a 10-second recording."""

    def __init__(self, model_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Enroll Speaker")
        self.setFixedSize(420, 340)
        self.setModal(True)

        self._model_path = model_path
        self.result_name: str = ""
        self.result_embeddings: list[list[float]] = []

        c = colors()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("Enroll New Speaker")
        title.setStyleSheet("font-size: 15px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel("Enter the speaker's name, then read the text aloud when recording.")
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        # Name field
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Speaker name")
        layout.addWidget(self._name_input)

        # Reading prompt
        self._prompt_label = QLabel()
        self._prompt_label.setWordWrap(True)
        self._prompt_label.setStyleSheet(
            f"QLabel {{"
            f"  font-size: 12px; font-style: italic;"
            f"  color: {c['TEXT_PRIMARY']};"
            f"  background: {c['BG_TERTIARY']};"
            f"  border-radius: 6px;"
            f"  padding: 8px 10px;"
            f"}}"
        )
        self._set_prompt("en")
        layout.addWidget(self._prompt_label)

        # Language toggle
        lang_row = QHBoxLayout()
        lang_row.setSpacing(6)
        lang_label = QLabel("Prompt:")
        lang_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        lang_row.addWidget(lang_label)
        for lang, label in (("en", "English"), ("fr", "Fran\u00e7ais")):
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 11px; padding: 2px 8px;"
                f" background: transparent; border: 1px solid {c['TEXT_SECONDARY']};"
                f" color: {c['TEXT_SECONDARY']}; border-radius: 4px; }}"
                f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
            )
            btn.clicked.connect(lambda _=False, lg=lang: self._set_prompt(lg))
            lang_row.addWidget(btn)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 100)
        self._progress.hide()
        self._progress.setStyleSheet(
            f"QProgressBar {{ background: {c['BG_TERTIARY']};"
            f" border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {c['ACCENT_BLUE']};"
            f" border-radius: 3px; }}"
        )
        layout.addWidget(self._progress)

        # Status label
        self._status = QLabel("")
        self._status.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._record_btn = QPushButton("Record")
        self._record_btn.setCursor(Qt.PointingHandCursor)
        self._record_btn.setStyleSheet(
            f"QPushButton {{ background: {c['ACCENT_BLUE']}; color: white;"
            f" border: none; border-radius: 6px; padding: 6px 16px; font-size: 13px; }}"
            f"QPushButton:hover {{ opacity: 0.9; }}"
        )
        self._record_btn.clicked.connect(self._start_recording)
        btn_row.addWidget(self._record_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

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
            self._status.setText("Please enter a name.")
            self._status.setStyleSheet(
                f"font-size: 12px; color: {colors()['ACCENT_RED']}; background: transparent;"
            )
            return

        self._record_btn.setEnabled(False)
        self._name_input.setEnabled(False)
        self._progress.show()
        self._progress.setValue(0)
        self._status.setText("Recording... speak now!")
        self._status.setStyleSheet(
            f"font-size: 12px; color: {colors()['TEXT_SECONDARY']}; background: transparent;"
        )

        loop = asyncio.get_event_loop()

        def _progress(pct: float) -> None:
            loop.call_soon_threadsafe(self._progress.setValue, int(pct * 100))

        async def _run() -> None:
            try:
                from roomkit_ui.enrollment import record_and_extract_multi

                embeddings = await record_and_extract_multi(
                    self._model_path, duration=10.0, progress=_progress
                )
                self.result_name = name
                self.result_embeddings = embeddings
                n = len(embeddings)
                self._status.setText(f"Done! Extracted {n} embedding{'s' if n != 1 else ''}.")
                self._status.setStyleSheet(
                    f"font-size: 12px; color: {colors()['ACCENT_GREEN']}; background: transparent;"
                )
                QTimer.singleShot(500, self.accept)
            except Exception as e:
                logger.exception("Enrollment failed")
                self._status.setText(f"Error: {e}")
                self._status.setStyleSheet(
                    f"font-size: 12px; color: {colors()['ACCENT_RED']}; background: transparent;"
                )
                self._record_btn.setEnabled(True)
                self._name_input.setEnabled(True)

        loop.create_task(_run())


class _SpeakerRow(QWidget):
    """A row for a single enrolled speaker."""

    def __init__(
        self,
        name: str,
        sample_count: int,
        is_primary: bool,
        c: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.speaker_name = name
        self._c = c

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        # Primary star
        self._star = QLabel("\u2605" if is_primary else "")
        self._star.setFixedWidth(16)
        self._star.setStyleSheet(
            f"font-size: 14px; color: {c['ACCENT_BLUE']}; background: transparent;"
        )
        row.addWidget(self._star)

        # Name
        name_label = QLabel(name)
        name_label.setStyleSheet("font-size: 13px; font-weight: 500; background: transparent;")
        row.addWidget(name_label)

        # Sample count
        count_label = QLabel(f"{sample_count} sample{'s' if sample_count != 1 else ''}")
        count_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        row.addWidget(count_label)

        row.addStretch()

        # Set Primary button
        self.primary_btn = QPushButton("Set Primary")
        self.primary_btn.setCursor(Qt.PointingHandCursor)
        self.primary_btn.setFixedHeight(24)
        self.primary_btn.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 8px;"
            f" background: transparent; border: 1px solid {c['ACCENT_BLUE']};"
            f" color: {c['ACCENT_BLUE']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {c['ACCENT_BLUE']}; color: white; }}"
        )
        if is_primary:
            self.primary_btn.hide()
        row.addWidget(self.primary_btn)

        # Add Sample button
        self.sample_btn = QPushButton("Add Sample")
        self.sample_btn.setCursor(Qt.PointingHandCursor)
        self.sample_btn.setFixedHeight(24)
        self.sample_btn.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 8px;"
            f" background: transparent; border: 1px solid {c['TEXT_SECONDARY']};"
            f" color: {c['TEXT_SECONDARY']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
        )
        row.addWidget(self.sample_btn)

        # Delete button
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setFixedHeight(24)
        self.delete_btn.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 2px 8px;"
            f" background: transparent; border: 1px solid {c['ACCENT_RED']};"
            f" color: {c['ACCENT_RED']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {c['ACCENT_RED']}; color: white; }}"
        )
        row.addWidget(self.delete_btn)

    def set_primary(self, is_primary: bool) -> None:
        self._star.setText("\u2605" if is_primary else "")
        self.primary_btn.setVisible(not is_primary)
