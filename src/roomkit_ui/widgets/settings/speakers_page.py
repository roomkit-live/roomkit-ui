"""Speakers settings page: enrollment, identification, and primary speaker mode."""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from roomkit_ui.widgets.settings.controls import (
    AdvancedSection,
    FeedbackLabel,
    SettingsForm,
    SettingsSection,
    SettingsToggle,
    label,
)
from roomkit_ui.widgets.settings.speakers_dialogs import _EnrollDialog, _SpeakerRow
from roomkit_ui.widgets.settings.speakers_muse import MuseSpeakersSection

logger = logging.getLogger(__name__)


class _SpeakersPage(QWidget):
    """Speakers settings tab: diarization toggle, model, threshold, enrollment."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(28)

        recognition = SettingsSection(
            "Speaker recognition",
            "Label who is talking in Voice Channel conversations. "
            "Realtime sessions run without speaker identification.",
        )
        self._enable_cb = SettingsToggle(
            "Identify speakers", bool(settings.get("diarization_enabled", False))
        )
        recognition.add_row(
            "Identify speakers",
            "Use enrolled voices with a local model, or let Meta Muse tell voices apart live.",
            self._enable_cb,
        )
        self._primary_cb = SettingsToggle(
            "Listen only to primary speaker", bool(settings.get("primary_speaker_mode", False))
        )
        recognition.add_row(
            "Listen only to primary speaker",
            "Only the primary voice triggers responses. Other and unrecognized voices stay "
            "in the chat but are not sent to the assistant. With Meta Muse, the voice "
            "carrying your name is primary.",
            self._primary_cb,
        )
        layout.addWidget(recognition)

        local = SettingsSection(
            "Local recognition",
            "Match each voice to a speaker enrolled with a 10-second sample. "
            "Meta Muse does not use this model or these samples.",
        )
        local.content.setContentsMargins(20, 20, 20, 20)
        local.content.setSpacing(16)
        form = SettingsForm()
        self._model_combo = QComboBox()
        self.refresh_models(settings.get("diarization_model", ""))
        form.addRow("Speaker model", self._model_combo)
        local.content.addLayout(form)
        self._model_hint = label("", "settingsHint")
        local.content.addWidget(self._model_hint)
        self._model_combo.currentIndexChanged.connect(self._update_model_hint)
        self._update_model_hint()

        tuning = QWidget()
        tuning_form = SettingsForm(tuning)
        threshold_control = QWidget()
        threshold_row = QHBoxLayout(threshold_control)
        threshold_row.setContentsMargins(0, 0, 0, 0)
        self._threshold_slider = QSlider(Qt.Horizontal)
        self._threshold_slider.setAccessibleName("Recognition threshold")
        self._threshold_slider.setRange(25, 65)
        try:
            threshold = float(settings.get("diarization_threshold", 0.4))
        except (ValueError, TypeError):
            threshold = 0.4
        self._threshold_slider.setValue(int(threshold * 100))
        self._threshold_slider.setTickInterval(10)
        threshold_row.addWidget(self._threshold_slider, 1)
        self._thresh_value = label(
            f"{self._threshold_slider.value() / 100:.2f}", "settingsHint", wrap=False
        )
        threshold_row.addWidget(self._thresh_value)
        self._threshold_slider.valueChanged.connect(
            lambda v: self._thresh_value.setText(f"{v / 100:.2f}")
        )
        tuning_form.addRow("Recognition threshold", threshold_control)
        tuning_form.addRow(label("Higher values require a closer voice match.", "settingsHint"))
        self.threshold_advanced = AdvancedSection("Recognition tuning", tuning)
        local.content.addWidget(self.threshold_advanced)
        layout.addWidget(local)

        enrolled = SettingsSection("Enrolled speakers", "Voice samples are stored on this device.")
        self._speakers_layout = enrolled.content
        self._speakers_layout.setContentsMargins(20, 18, 20, 18)
        self._speakers_layout.setSpacing(16)
        self._speaker_rows: list[_SpeakerRow] = []
        self._refresh_speakers()
        layout.addWidget(enrolled)

        actions = QHBoxLayout()
        self._enroll_btn = QPushButton("Enroll speaker")
        self._enroll_btn.clicked.connect(self._on_enroll)
        self._test_btn = QPushButton("Test recognition · 3s")
        self._test_btn.clicked.connect(self._on_test)
        for button in (self._enroll_btn, self._test_btn):
            button.setAutoDefault(False)
            button.setCursor(Qt.PointingHandCursor)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self._test_result = FeedbackLabel()
        layout.addWidget(self._test_result)

        self._muse = MuseSpeakersSection(settings)
        layout.addWidget(self._muse)
        layout.addStretch()

    def refresh_models(self, selected: str | None = None) -> None:
        from roomkit_ui.model_manager import SPEAKER_MODELS, is_speaker_model_downloaded

        selected = self._model_combo.currentData() if selected is None else selected
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItem("None", "")
        for model in SPEAKER_MODELS:
            state = "Downloaded" if is_speaker_model_downloaded(model.id) else "Not downloaded"
            self._model_combo.addItem(f"{model.name} · {state}", model.id)
        if selected and self._model_combo.findData(selected) < 0:
            self._model_combo.addItem(f"{selected} (unavailable)", selected)
        self._model_combo.setCurrentIndex(max(0, self._model_combo.findData(selected or "")))
        self._model_combo.blockSignals(False)
        if hasattr(self, "_model_hint"):
            self._update_model_hint()

    def _update_model_hint(self) -> None:
        self._model_hint.setText(
            "Ready to enroll and recognize voices."
            if self._get_model_path()
            else "Select a downloaded speaker model to enroll or test voices. "
            "Downloads are in Models & components."
        )

    def _refresh_speakers(self) -> None:
        """Rebuild the enrolled speakers list."""
        # Clear existing rows
        while self._speakers_layout.count():
            item = self._speakers_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._speaker_rows.clear()

        from roomkit_ui.speaker_manager import load_speakers

        speakers = load_speakers()

        if not speakers:
            self._speakers_layout.addWidget(
                label(
                    "No speakers enrolled yet. Add a voice sample to recognize someone "
                    "in your conversations.",
                    "settingsHint",
                )
            )
            return

        for sp in speakers:
            row = _SpeakerRow(sp.name, len(sp.embeddings), sp.is_primary)
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
            self._show_test_result("Select and download a speaker model first.", "error")
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

    def _set_primary(self, name: str) -> None:
        from roomkit_ui.speaker_manager import set_primary_speaker

        set_primary_speaker(name)
        self._refresh_speakers()

    def _add_sample(self, name: str) -> None:
        model_path = self._get_model_path()
        if model_path is None:
            self._show_test_result("Select and download a speaker model first.", "error")
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
                if not isValid(self):
                    return  # the Settings dialog closed during the recording

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
                if isValid(self):
                    self._show_test_result(f"Error: {exc}", "error")
            finally:
                if isValid(self):
                    self._test_btn.setEnabled(True)
                    self._test_btn.setText("Test recognition · 3s")

        loop.create_task(_run())

    def _show_test_result(self, text: str, level: str = "info") -> None:
        self._test_result.set_status(text, level if level in {"success", "error"} else "neutral")

    def get_settings(self) -> dict:
        return {
            "diarization_enabled": self._enable_cb.isChecked(),
            "diarization_model": self._model_combo.currentData() or "",
            "diarization_threshold": self._threshold_slider.value() / 100.0,
            "primary_speaker_mode": self._primary_cb.isChecked(),
            **self._muse.get_settings(),
        }
