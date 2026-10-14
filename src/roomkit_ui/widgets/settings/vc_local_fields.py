"""Voice Channel local provider fields: local STT, Piper and Kokoro TTS, voice clone,
Pocket, Vui.

A local LLM's fields are ``llm_fields.LLMFields``, as in every place a model is
chosen."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

_MODEL_MISSING_ROLE = Qt.UserRole + 1


class VCLocalFields:
    """Local provider fields added to a parent QFormLayout in phases.

    Call ``add_stt_fields``, ``add_tts_fields`` at the
    correct insertion points in the form so rows interleave properly with
    the provider selectors owned by the orchestrator.
    """

    def __init__(self, parent_widget: QWidget, settings: dict) -> None:
        self._parent = parent_widget
        self._settings = settings

    def add_stt_fields(self, form: QFormLayout) -> None:
        self.vc_stt_model = QComboBox()
        self._vc_stt_model_label = QLabel("STT Model")
        self._vc_stt_no_models = QLabel(
            "No STT models downloaded \u2014 open Models & components."
        )
        self._vc_stt_no_models.setWordWrap(True)
        self._vc_stt_no_models.setObjectName("settingsHint")
        form.addRow(self._vc_stt_model_label, self.vc_stt_model)
        form.addRow("", self._vc_stt_no_models)
        self._vc_saved_stt = self._settings.get("vc_stt_model", "")

    def add_tts_fields(self, form: QFormLayout) -> None:
        s = self._settings

        # Piper model combo
        self.vc_tts_model = QComboBox()
        self._vc_tts_model_label = QLabel("TTS Model")
        self._vc_tts_no_models = QLabel(
            "No TTS models downloaded \u2014 open Models & components."
        )
        self._vc_tts_no_models.setWordWrap(True)
        self._vc_tts_no_models.setObjectName("settingsHint")
        form.addRow(self._vc_tts_model_label, self.vc_tts_model)
        form.addRow("", self._vc_tts_no_models)
        self._vc_saved_tts = s.get("vc_tts_model", "")

        # Voice clone reference fields (Qwen3 / NeuTTS)
        self.vc_tts_ref_audio = QLineEdit(s.get("vc_tts_ref_audio", ""))
        self.vc_tts_ref_audio.setPlaceholderText("Path to reference WAV (3-15s of speech)")
        self._vc_ref_audio_browse = QPushButton("Browse\u2026")
        self._vc_ref_audio_browse.setCursor(Qt.PointingHandCursor)
        self._vc_ref_audio_browse.setAutoDefault(False)
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

        self._add_kokoro_fields(form)
        self._add_pocket_fields(form)
        self._add_vui_fields(form)

    def _add_pocket_fields(self, form: QFormLayout) -> None:
        """Pocket TTS: a language model, and a pre-made voice or a clip to clone."""
        from roomkit_ui.tts.pocket import LANGUAGES

        s = self._settings
        self.vc_pocket_language = QComboBox()
        for label, value in LANGUAGES:
            self.vc_pocket_language.addItem(label, value)
        index = self.vc_pocket_language.findData(s.get("vc_pocket_language", ""))
        self.vc_pocket_language.setCurrentIndex(max(index, 0))
        self._vc_pocket_language_label = QLabel("Language")
        form.addRow(self._vc_pocket_language_label, self.vc_pocket_language)

        self.vc_pocket_voice = QLineEdit(s.get("vc_pocket_voice", ""))
        self.vc_pocket_voice.setPlaceholderText("alba (English), estelle (French), or a clip")
        self.vc_pocket_voice.setToolTip(
            "A pre-made Pocket TTS voice (alba, estelle, marius, cosette… — see "
            "huggingface.co/kyutai/tts-voices), or a short, clean WAV of the voice to "
            "clone. Cloning needs the gated kyutai/pocket-tts weights: accept their terms "
            "on Hugging Face, then log in on this machine (hf auth login)."
        )
        self._vc_pocket_browse = QPushButton("Browse…")
        self._vc_pocket_browse.setCursor(Qt.PointingHandCursor)
        self._vc_pocket_browse.setAutoDefault(False)
        self._vc_pocket_browse.clicked.connect(self._browse_pocket_clip)
        voice_row = QHBoxLayout()
        voice_row.setSpacing(6)
        voice_row.addWidget(self.vc_pocket_voice, 1)
        voice_row.addWidget(self._vc_pocket_browse)
        self._vc_pocket_voice_label = QLabel("Voice")
        form.addRow(self._vc_pocket_voice_label, voice_row)

    def _add_kokoro_fields(self, form: QFormLayout) -> None:
        """Kokoro: a voice, whose language it speaks; by default the STT language's."""
        from roomkit_ui.tts.kokoro import VOICES

        self.vc_kokoro_voice = QComboBox()
        self.vc_kokoro_voice.addItem("Same language as speech recognition", "")
        for label, name in VOICES:
            self.vc_kokoro_voice.addItem(label, name)
        index = self.vc_kokoro_voice.findData(self._settings.get("vc_kokoro_voice", ""))
        self.vc_kokoro_voice.setCurrentIndex(max(index, 0))
        self._vc_kokoro_voice_label = QLabel("Voice")
        form.addRow(self._vc_kokoro_voice_label, self.vc_kokoro_voice)
        self._vc_kokoro_missing = QLabel("Download Kokoro in Models & components.")
        self._vc_kokoro_missing.setWordWrap(True)
        self._vc_kokoro_missing.setObjectName("settingsHint")
        form.addRow("", self._vc_kokoro_missing)

    def _add_vui_fields(self, form: QFormLayout) -> None:
        """Vui: one of its voices, or the clip in Ref Audio and Ref Text."""
        from roomkit_ui.tts.vui import CLONE, PRESETS

        self.vc_vui_voice = QComboBox()
        for name in PRESETS:
            self.vc_vui_voice.addItem(name.capitalize(), name)
        self.vc_vui_voice.addItem("Clone the clip below", CLONE)
        index = self.vc_vui_voice.findData(self._settings.get("vc_vui_voice", ""))
        self.vc_vui_voice.setCurrentIndex(max(index, 0))
        self.vc_vui_voice.setToolTip(
            "Vui speaks English only, on an NVIDIA GPU. Cloning takes a clean clip "
            "under 15 seconds and its exact transcript."
        )
        self._vc_vui_voice_label = QLabel("Voice")
        form.addRow(self._vc_vui_voice_label, self.vc_vui_voice)
        self._tts_provider = ""
        self.vc_vui_voice.currentIndexChanged.connect(
            lambda: self.update_tts_visibility(self._tts_provider)
        )

    # -- Visibility --

    def update_stt_visibility(self, provider: str) -> None:
        is_local = provider == "local"
        self._vc_stt_model_label.setVisible(is_local and self.vc_stt_model.count() > 0)
        self.vc_stt_model.setVisible(is_local and self.vc_stt_model.count() > 0)
        missing = bool(self.vc_stt_model.currentData(_MODEL_MISSING_ROLE))
        self._vc_stt_no_models.setText(
            "Download the selected STT model in Models & components."
            if missing
            else "No STT models downloaded — open Models & components."
        )
        self._vc_stt_no_models.setVisible(is_local and (missing or self.vc_stt_model.count() == 0))

    def update_tts_visibility(self, provider: str) -> None:
        from roomkit_ui.tts.vui import CLONE

        self._tts_provider = provider
        is_piper = provider == "piper"
        is_vui = provider == "vui"
        is_voice_clone = provider in ("qwen3", "neutts") or (
            is_vui and self.vc_vui_voice.currentData() == CLONE
        )
        self._vc_tts_model_label.setVisible(is_piper and self.vc_tts_model.count() > 0)
        self.vc_tts_model.setVisible(is_piper and self.vc_tts_model.count() > 0)
        missing = bool(self.vc_tts_model.currentData(_MODEL_MISSING_ROLE))
        self._vc_tts_no_models.setText(
            "Download the selected voice in Models & components."
            if missing
            else "No TTS models downloaded — open Models & components."
        )
        self._vc_tts_no_models.setVisible(is_piper and (missing or self.vc_tts_model.count() == 0))
        self._vc_ref_audio_label.setVisible(is_voice_clone)
        self.vc_tts_ref_audio.setVisible(is_voice_clone)
        self._vc_ref_audio_browse.setVisible(is_voice_clone)
        self._vc_ref_text_label.setVisible(is_voice_clone)
        self.vc_tts_ref_text.setVisible(is_voice_clone)
        is_pocket = provider == "pocket"
        for widget in (
            self._vc_pocket_language_label,
            self.vc_pocket_language,
            self._vc_pocket_voice_label,
            self.vc_pocket_voice,
            self._vc_pocket_browse,
        ):
            widget.setVisible(is_pocket)
        self._vc_vui_voice_label.setVisible(is_vui)
        self.vc_vui_voice.setVisible(is_vui)
        self._update_kokoro_visibility(provider == "kokoro")

    def _update_kokoro_visibility(self, is_kokoro: bool) -> None:
        from roomkit_ui.model_catalog import is_kokoro_downloaded

        self._vc_kokoro_voice_label.setVisible(is_kokoro)
        self.vc_kokoro_voice.setVisible(is_kokoro)
        self._vc_kokoro_missing.setVisible(is_kokoro and not is_kokoro_downloaded())

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
        missing_stt = bool(target and self.vc_stt_model.findData(target) < 0)
        if missing_stt:
            name = next((model.name for model in STT_MODELS if model.id == target), target)
            self.vc_stt_model.addItem(f"{name} — not downloaded", target)
            self.vc_stt_model.setItemData(self.vc_stt_model.count() - 1, True, _MODEL_MISSING_ROLE)
        for i in range(self.vc_stt_model.count()):
            if self.vc_stt_model.itemData(i) == target:
                self.vc_stt_model.setCurrentIndex(i)
                break
        self.vc_stt_model.blockSignals(False)

        # TTS
        self.vc_tts_model.blockSignals(True)
        self.vc_tts_model.clear()
        for tm in TTS_MODELS:
            if is_tts_model_downloaded(tm.id):
                self.vc_tts_model.addItem(tm.name, tm.id)
        target = saved_tts or (self.vc_tts_model.itemData(0) if self.vc_tts_model.count() else "")
        missing_tts = bool(target and self.vc_tts_model.findData(target) < 0)
        if missing_tts:
            name = next((model.name for model in TTS_MODELS if model.id == target), target)
            self.vc_tts_model.addItem(f"{name} — not downloaded", target)
            self.vc_tts_model.setItemData(self.vc_tts_model.count() - 1, True, _MODEL_MISSING_ROLE)
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

    def _browse_pocket_clip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self._parent, "Select a Voice to Clone", "", "WAV files (*.wav)"
        )
        if path:
            self.vc_pocket_voice.setText(path)

    # -- Settings --

    def get_settings(self) -> dict:
        return {
            "vc_stt_model": self.vc_stt_model.currentData() or "",
            "vc_tts_model": self.vc_tts_model.currentData() or "",
            "vc_tts_ref_audio": self.vc_tts_ref_audio.text().strip(),
            "vc_tts_ref_text": self.vc_tts_ref_text.text().strip(),
            "vc_pocket_language": self.vc_pocket_language.currentData() or "",
            "vc_pocket_voice": self.vc_pocket_voice.text().strip(),
            "vc_vui_voice": self.vc_vui_voice.currentData() or "",
            "vc_kokoro_voice": self.vc_kokoro_voice.currentData() or "",
        }
