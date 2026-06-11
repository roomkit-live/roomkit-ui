"""Speakers settings page: enrollment, identification, and primary speaker mode."""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.widgets.settings.speakers_dialogs import _EnrollDialog, _SpeakerRow

logger = logging.getLogger(__name__)


class _SpeakersPage(QWidget):
    """Speakers settings tab: diarization toggle, model, threshold, enrollment."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("Speakers")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel(
            "Enable speaker identification to label who is talking in the chat. "
            "Enroll speakers by recording a 10-second voice sample."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        # -- Enable toggle --
        self._enable_cb = QCheckBox("Enable Speaker Identification")
        self._enable_cb.setChecked(settings.get("diarization_enabled", False))
        layout.addWidget(self._enable_cb)

        # -- Model selection --
        model_row = QHBoxLayout()
        model_label = QLabel("Speaker Model:")
        model_label.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        model_row.addWidget(model_label)

        self._model_combo = QComboBox()
        self._model_combo.addItem("(none)", "")
        from roomkit_ui.model_manager import SPEAKER_MODELS, is_speaker_model_downloaded

        for sm in SPEAKER_MODELS:
            suffix = " (downloaded)" if is_speaker_model_downloaded(sm.id) else ""
            self._model_combo.addItem(f"{sm.name}{suffix}", sm.id)

        current_model = settings.get("diarization_model", "")
        idx = self._model_combo.findData(current_model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        model_row.addWidget(self._model_combo, 1)
        layout.addLayout(model_row)

        # -- Threshold slider --
        thresh_row = QHBoxLayout()
        thresh_label = QLabel("Recognition Threshold:")
        thresh_label.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        thresh_row.addWidget(thresh_label)

        self._threshold_slider = QSlider(Qt.Horizontal)
        self._threshold_slider.setRange(25, 65)
        threshold = settings.get("diarization_threshold", 0.4)
        if isinstance(threshold, str):
            try:
                threshold = float(threshold)
            except (ValueError, TypeError):
                threshold = 0.4
        self._threshold_slider.setValue(int(threshold * 100))
        self._threshold_slider.setTickInterval(10)
        thresh_row.addWidget(self._threshold_slider, 1)

        self._thresh_value = QLabel(f"{threshold:.2f}")
        self._thresh_value.setFixedWidth(36)
        self._thresh_value.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        thresh_row.addWidget(self._thresh_value)
        self._threshold_slider.valueChanged.connect(
            lambda v: self._thresh_value.setText(f"{v / 100:.2f}")
        )
        layout.addLayout(thresh_row)

        # -- Primary speaker mode --
        self._primary_cb = QCheckBox("Listen only to primary speaker")
        self._primary_cb.setChecked(settings.get("primary_speaker_mode", False))
        layout.addWidget(self._primary_cb)

        primary_desc = QLabel(
            "When enabled, only the primary speaker's voice triggers AI responses. "
            "Other speakers' words are shown but not sent to the assistant."
        )
        primary_desc.setWordWrap(True)
        primary_desc.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(primary_desc)

        # -- Enrolled speakers section --
        speakers_section = QLabel("Enrolled Speakers")
        speakers_section.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(speakers_section)

        self._speakers_frame = QWidget()
        self._speakers_frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        self._speakers_layout = QVBoxLayout(self._speakers_frame)
        self._speakers_layout.setContentsMargins(4, 4, 4, 4)
        self._speakers_layout.setSpacing(0)

        self._speaker_rows: list[_SpeakerRow] = []
        self._refresh_speakers()
        layout.addWidget(self._speakers_frame)

        # -- Enroll button --
        self._enroll_btn = QPushButton("+ Enroll New Speaker")
        self._enroll_btn.setCursor(Qt.PointingHandCursor)
        self._enroll_btn.setStyleSheet(
            f"QPushButton {{ font-size: 13px; padding: 8px 16px;"
            f" background: {c['ACCENT_BLUE']}; color: white;"
            f" border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ opacity: 0.9; }}"
        )
        self._enroll_btn.clicked.connect(self._on_enroll)
        layout.addWidget(self._enroll_btn)

        # -- Test Recognition button --
        self._test_btn = QPushButton("Test Recognition")
        self._test_btn.setCursor(Qt.PointingHandCursor)
        self._test_btn.setStyleSheet(
            f"QPushButton {{ font-size: 13px; padding: 8px 16px;"
            f" background: {c['BG_TERTIARY']}; color: {c['TEXT_PRIMARY']};"
            f" border: 1px solid {c['SEPARATOR']}; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {c['BG_SECONDARY']}; }}"
        )
        self._test_btn.clicked.connect(self._on_test)
        layout.addWidget(self._test_btn)

        # Test result label
        self._test_result = QLabel("")
        self._test_result.setWordWrap(True)
        self._test_result.setAlignment(Qt.AlignCenter)
        self._test_result.setStyleSheet(
            f"font-size: 13px; background: transparent; color: {c['TEXT_SECONDARY']};"
        )
        self._test_result.hide()
        layout.addWidget(self._test_result)

        layout.addStretch()

    def _refresh_speakers(self) -> None:
        """Rebuild the enrolled speakers list."""
        # Clear existing rows
        while self._speakers_layout.count():
            item = self._speakers_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._speaker_rows.clear()

        from roomkit_ui.speaker_manager import load_speakers

        c = colors()
        speakers = load_speakers()

        if not speakers:
            empty = QLabel("No speakers enrolled yet.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(
                f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
                f" background: transparent; padding: 12px;"
            )
            self._speakers_layout.addWidget(empty)
            return

        for sp in speakers:
            row = _SpeakerRow(sp.name, len(sp.embeddings), sp.is_primary, c)
            row.primary_btn.clicked.connect(lambda _=False, n=sp.name: self._set_primary(n))
            row.sample_btn.clicked.connect(lambda _=False, n=sp.name: self._add_sample(n))
            row.delete_btn.clicked.connect(lambda _=False, n=sp.name: self._delete_speaker(n))
            self._speakers_layout.addWidget(row)
            self._speaker_rows.append(row)

    def _get_model_path(self) -> str | None:
        """Return the ONNX model path for the selected speaker model."""
        model_id = self._model_combo.currentData()
        if not model_id:
            return None
        from roomkit_ui.model_manager import is_speaker_model_downloaded, speaker_model_path

        if not is_speaker_model_downloaded(model_id):
            return None
        from roomkit_ui.model_manager import _SPEAKER_MODELS_BY_ID

        m = _SPEAKER_MODELS_BY_ID.get(model_id)
        if m is None:
            return None
        return str(speaker_model_path(model_id) / m.onnx_file)

    def _on_enroll(self) -> None:
        model_path = self._get_model_path()
        if model_path is None:
            c = colors()
            # Brief visual hint — no model selected or not downloaded
            self._enroll_btn.setText("Download a speaker model first!")
            self._enroll_btn.setStyleSheet(
                f"QPushButton {{ font-size: 13px; padding: 8px 16px;"
                f" background: {c['ACCENT_RED']}; color: white;"
                f" border: none; border-radius: 8px; }}"
            )
            QTimer.singleShot(2000, self._reset_enroll_btn)
            return

        dlg = _EnrollDialog(model_path, self)
        if dlg.exec() == QDialog.Accepted and dlg.result_name and dlg.result_embeddings:
            from roomkit_ui.speaker_manager import SpeakerProfile, load_speakers, save_speaker

            # Check if speaker already exists → add samples
            existing = [s for s in load_speakers() if s.name == dlg.result_name]
            if existing:
                existing[0].embeddings.extend(dlg.result_embeddings)
                save_speaker(existing[0])
            else:
                profile = SpeakerProfile(
                    name=dlg.result_name,
                    embeddings=dlg.result_embeddings,
                    is_primary=not any(s.is_primary for s in load_speakers()),
                )
                save_speaker(profile)
            self._refresh_speakers()

    def _reset_enroll_btn(self) -> None:
        c = colors()
        self._enroll_btn.setText("+ Enroll New Speaker")
        self._enroll_btn.setStyleSheet(
            f"QPushButton {{ font-size: 13px; padding: 8px 16px;"
            f" background: {c['ACCENT_BLUE']}; color: white;"
            f" border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ opacity: 0.9; }}"
        )

    def _set_primary(self, name: str) -> None:
        from roomkit_ui.speaker_manager import set_primary_speaker

        set_primary_speaker(name)
        self._refresh_speakers()

    def _add_sample(self, name: str) -> None:
        model_path = self._get_model_path()
        if model_path is None:
            return

        dlg = _EnrollDialog(model_path, self)
        # Pre-fill name and disable editing
        dlg._name_input.setText(name)
        dlg._name_input.setEnabled(False)
        if dlg.exec() == QDialog.Accepted and dlg.result_embeddings:
            from roomkit_ui.speaker_manager import load_speakers, save_speaker

            existing = [s for s in load_speakers() if s.name == name]
            if existing:
                existing[0].embeddings.extend(dlg.result_embeddings)
                save_speaker(existing[0])
            self._refresh_speakers()

    def _delete_speaker(self, name: str) -> None:
        from roomkit_ui.speaker_manager import delete_speaker

        delete_speaker(name)
        self._refresh_speakers()

    def _on_test(self) -> None:
        """Record 3 seconds and identify the speaker against enrolled profiles."""
        model_path = self._get_model_path()
        if model_path is None:
            self._show_test_result("Select and download a speaker model first.", "error")
            return

        from roomkit_ui.speaker_manager import load_speakers

        speakers = load_speakers()
        if not speakers:
            self._show_test_result("No speakers enrolled. Enroll someone first.", "error")
            return

        self._test_btn.setEnabled(False)
        self._test_btn.setText("Recording 3s...")
        self._test_result.hide()

        threshold = self._threshold_slider.value() / 100.0
        loop = asyncio.get_event_loop()

        async def _run() -> None:
            try:
                from roomkit_ui.enrollment import record_and_extract

                embedding = await record_and_extract(model_path, duration=3.0, progress=None)

                # Compute cosine similarity manually for each enrolled speaker
                import math

                def _cosine_sim(a: list[float], b: list[float]) -> float:
                    dot = sum(x * y for x, y in zip(a, b, strict=False))
                    na = math.sqrt(sum(x * x for x in a))
                    nb = math.sqrt(sum(x * x for x in b))
                    return dot / (na * nb) if na > 0 and nb > 0 else 0.0

                lines: list[str] = []
                best_name = ""
                best_score = 0.0

                for sp in speakers:
                    if not sp.embeddings:
                        continue
                    # Score against each enrolled embedding, take the best
                    scores = [_cosine_sim(embedding, e) for e in sp.embeddings]
                    avg_score = sum(scores) / len(scores)
                    max_score = max(scores)
                    lines.append(
                        f"{sp.name}: best={max_score:.3f} avg={avg_score:.3f}"
                        f" ({len(sp.embeddings)} sample{'s' if len(sp.embeddings) != 1 else ''})"
                    )
                    if max_score > best_score:
                        best_score = max_score
                        best_name = sp.name

                score_report = "\n".join(lines)

                if best_score >= threshold:
                    self._show_test_result(
                        f"Recognized: {best_name} (score {best_score:.3f})\n{score_report}",
                        "success",
                    )
                elif best_score > 0.2:
                    self._show_test_result(
                        f"Best: {best_name} (score {best_score:.3f},"
                        f" threshold {threshold:.2f})\n{score_report}",
                        "warning",
                    )
                else:
                    self._show_test_result(
                        f"No match found\n{score_report}",
                        "warning",
                    )
            except Exception as exc:
                logger.exception("Test recognition failed")
                self._show_test_result(f"Error: {exc}", "error")
            finally:
                self._test_btn.setEnabled(True)
                self._test_btn.setText("Test Recognition")

        loop.create_task(_run())

    def _show_test_result(self, text: str, level: str = "info") -> None:
        c = colors()
        if level == "success":
            color = c["ACCENT_GREEN"]
        elif level == "error":
            color = c["ACCENT_RED"]
        elif level == "warning":
            color = "#FF9F0A"  # orange
        else:
            color = c["TEXT_SECONDARY"]
        self._test_result.setText(text)
        self._test_result.setStyleSheet(
            f"font-size: 13px; font-weight: 500; background: transparent; color: {color};"
        )
        self._test_result.show()

    def get_settings(self) -> dict:
        return {
            "diarization_enabled": self._enable_cb.isChecked(),
            "diarization_model": self._model_combo.currentData() or "",
            "diarization_threshold": self._threshold_slider.value() / 100.0,
            "primary_speaker_mode": self._primary_cb.isChecked(),
        }
