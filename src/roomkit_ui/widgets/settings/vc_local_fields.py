"""Voice Channel local provider fields: local LLM, local STT, Piper TTS, voice clone."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from roomkit_ui.theme import colors


class VCLocalFields:
    """Local provider fields added to a parent QFormLayout in phases.

    Call ``add_llm_fields``, ``add_stt_fields``, ``add_tts_fields`` at the
    correct insertion points in the form so rows interleave properly with
    the provider selectors owned by the orchestrator.
    """

    def __init__(self, parent_widget: QWidget, settings: dict) -> None:
        self._parent = parent_widget
        self._settings = settings

    def add_llm_fields(self, form: QFormLayout) -> None:
        s = self._settings
        self.vc_local_base_url = QLineEdit(s.get("vc_local_base_url", ""))
        self.vc_local_base_url.setPlaceholderText("http://localhost:11434/v1")
        self._vc_local_base_url_label = QLabel("Base URL")
        form.addRow(self._vc_local_base_url_label, self.vc_local_base_url)

        self.vc_local_model = QLineEdit(s.get("vc_local_model", ""))
        self.vc_local_model.setPlaceholderText("e.g. qwen2.5:7b")
        self._vc_local_model_label = QLabel("Model")
        form.addRow(self._vc_local_model_label, self.vc_local_model)

        self.vc_local_api_key = QLineEdit(s.get("vc_local_api_key", ""))
        self.vc_local_api_key.setEchoMode(QLineEdit.Password)
        self.vc_local_api_key.setPlaceholderText("Optional")
        self._vc_local_api_key_label = QLabel("API Key")
        form.addRow(self._vc_local_api_key_label, self.vc_local_api_key)

        self.vc_local_tools = QCheckBox("Model supports tool use (function calling)")
        self.vc_local_tools.setChecked(bool(s.get("vc_local_tools", True)))
        self._vc_local_tools_label = QLabel("")
        form.addRow(self._vc_local_tools_label, self.vc_local_tools)

    def add_stt_fields(self, form: QFormLayout) -> None:
        c = colors()
        self.vc_stt_model = QComboBox()
        self._vc_stt_model_label = QLabel("STT Model")
        self._vc_stt_no_models = QLabel("No STT models downloaded \u2014 go to AI Models tab.")
        self._vc_stt_no_models.setWordWrap(True)
        self._vc_stt_no_models.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        form.addRow(self._vc_stt_model_label, self.vc_stt_model)
        form.addRow("", self._vc_stt_no_models)
        self._vc_saved_stt = self._settings.get("vc_stt_model", "")

    def add_tts_fields(self, form: QFormLayout) -> None:
        s = self._settings
        c = colors()

        # Piper model combo
        self.vc_tts_model = QComboBox()
        self._vc_tts_model_label = QLabel("TTS Model")
        self._vc_tts_no_models = QLabel("No TTS models downloaded \u2014 go to AI Models tab.")
        self._vc_tts_no_models.setWordWrap(True)
        self._vc_tts_no_models.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        form.addRow(self._vc_tts_model_label, self.vc_tts_model)
        form.addRow("", self._vc_tts_no_models)
        self._vc_saved_tts = s.get("vc_tts_model", "")

        # Voice clone reference fields (Qwen3 / NeuTTS)
        self.vc_tts_ref_audio = QLineEdit(s.get("vc_tts_ref_audio", ""))
        self.vc_tts_ref_audio.setPlaceholderText("Path to reference WAV (3-15s of speech)")
        self._vc_ref_audio_browse = QPushButton("Browse\u2026")
        self._vc_ref_audio_browse.setCursor(Qt.PointingHandCursor)
        self._vc_ref_audio_browse.setFixedHeight(28)
        self._vc_ref_audio_browse.clicked.connect(self._browse_ref_audio)
        ref_audio_row = QHBoxLayout()
        ref_audio_row.setSpacing(6)
        ref_audio_row.addWidget(self.vc_tts_ref_audio, 1)
        ref_audio_row.addWidget(self._vc_ref_audio_browse)
        self._vc_ref_audio_label = QLabel("Ref Audio")
        form.addRow(self._vc_ref_audio_label, ref_audio_row)

        self.vc_tts_ref_text = QLineEdit(s.get("vc_tts_ref_text", ""))
        self.vc_tts_ref_text.setPlaceholderText("Transcript of the reference audio")
        self._vc_ref_text_label = QLabel("Ref Text")
        form.addRow(self._vc_ref_text_label, self.vc_tts_ref_text)

    # -- Visibility --

    def update_llm_visibility(self, provider: str) -> None:
        is_local = provider == "local"
        self._vc_local_base_url_label.setVisible(is_local)
        self.vc_local_base_url.setVisible(is_local)
        self._vc_local_model_label.setVisible(is_local)
        self.vc_local_model.setVisible(is_local)
        self._vc_local_api_key_label.setVisible(is_local)
        self.vc_local_api_key.setVisible(is_local)
        self._vc_local_tools_label.setVisible(is_local)
        self.vc_local_tools.setVisible(is_local)

    def update_stt_visibility(self, provider: str) -> None:
        is_local = provider == "local"
        self._vc_stt_model_label.setVisible(is_local)
        self.vc_stt_model.setVisible(is_local)
        self._vc_stt_no_models.setVisible(is_local and self.vc_stt_model.count() == 0)

    def update_tts_visibility(self, provider: str) -> None:
        is_piper = provider == "piper"
        is_voice_clone = provider in ("qwen3", "neutts")
        self._vc_tts_model_label.setVisible(is_piper)
        self.vc_tts_model.setVisible(is_piper)
        self._vc_tts_no_models.setVisible(is_piper and self.vc_tts_model.count() == 0)
        self._vc_ref_audio_label.setVisible(is_voice_clone)
        self.vc_tts_ref_audio.setVisible(is_voice_clone)
        self._vc_ref_audio_browse.setVisible(is_voice_clone)
        self._vc_ref_text_label.setVisible(is_voice_clone)
        self.vc_tts_ref_text.setVisible(is_voice_clone)

    # -- Model combos --

    def refresh_model_combos(self, saved_stt: str, saved_tts: str) -> None:
        from roomkit_ui.model_manager import (
            STT_MODELS,
            TTS_MODELS,
            is_model_downloaded,
            is_tts_model_downloaded,
        )

        # STT
        self.vc_stt_model.blockSignals(True)
        self.vc_stt_model.clear()
        for m in STT_MODELS:
            if is_model_downloaded(m.id):
                self.vc_stt_model.addItem(f"{m.name} ({m.type})", m.id)
        target = saved_stt or (self.vc_stt_model.itemData(0) if self.vc_stt_model.count() else "")
        for i in range(self.vc_stt_model.count()):
            if self.vc_stt_model.itemData(i) == target:
                self.vc_stt_model.setCurrentIndex(i)
                break
        self.vc_stt_model.blockSignals(False)
        self._vc_stt_no_models.setVisible(self.vc_stt_model.count() == 0)

        # TTS
        self.vc_tts_model.blockSignals(True)
        self.vc_tts_model.clear()
        for tm in TTS_MODELS:
            if is_tts_model_downloaded(tm.id):
                self.vc_tts_model.addItem(tm.name, tm.id)
        target = saved_tts or (self.vc_tts_model.itemData(0) if self.vc_tts_model.count() else "")
        for i in range(self.vc_tts_model.count()):
            if self.vc_tts_model.itemData(i) == target:
                self.vc_tts_model.setCurrentIndex(i)
                break
        self.vc_tts_model.blockSignals(False)

    def _browse_ref_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self._parent, "Select Reference Audio", "", "WAV files (*.wav)"
        )
        if path:
            self.vc_tts_ref_audio.setText(path)

    # -- Settings --

    def get_settings(self) -> dict:
        return {
            "vc_local_base_url": self.vc_local_base_url.text().strip(),
            "vc_local_model": self.vc_local_model.text().strip(),
            "vc_local_api_key": self.vc_local_api_key.text().strip(),
            "vc_local_tools": self.vc_local_tools.isChecked(),
            "vc_stt_model": self.vc_stt_model.currentData() or "",
            "vc_tts_model": self.vc_tts_model.currentData() or "",
            "vc_tts_ref_audio": self.vc_tts_ref_audio.text().strip(),
            "vc_tts_ref_text": self.vc_tts_ref_text.text().strip(),
        }
