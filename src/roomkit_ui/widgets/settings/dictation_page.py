"""Dictation settings: enable, STT provider, hotkey, language."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.widgets.hotkey_button import HotkeyButton
from roomkit_ui.widgets.settings.constants import STT_LANGUAGES, STT_PROVIDERS


class _DictationPage(QWidget):
    """Dictation settings: enable, STT provider, hotkey, language."""

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("Dictation")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        desc = QLabel(
            "Press a global hotkey to record speech and paste the "
            "transcription into the focused input field."
        )
        desc.setWordWrap(True)
        c = colors()
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        # Enable
        self.enabled = QCheckBox("Enable dictation")
        self.enabled.setChecked(bool(settings.get("stt_enabled", True)))
        form.addRow("", self.enabled)

        # STT Provider
        self.stt_provider = QComboBox()
        for label, _value in STT_PROVIDERS:
            self.stt_provider.addItem(label)
        current_stt = settings.get("stt_provider", "openai")
        for i, (_, val) in enumerate(STT_PROVIDERS):
            if val == current_stt:
                self.stt_provider.setCurrentIndex(i)
                break
        form.addRow("STT Provider", self.stt_provider)

        # OpenAI API key (shown only for OpenAI provider)
        self.openai_api_key = QLineEdit(settings.get("openai_api_key", ""))
        self.openai_api_key.setEchoMode(QLineEdit.Password)
        self.openai_api_key.setPlaceholderText("Required for dictation STT")
        self._openai_key_label = QLabel("OpenAI Key")
        form.addRow(self._openai_key_label, self.openai_api_key)

        # Local model combo (shown only for Local provider)
        self._model_combo = QComboBox()
        self._model_label = QLabel("Model")
        form.addRow(self._model_label, self._model_combo)

        self._no_models_hint = QLabel(
            "No models downloaded \u2014 go to the AI Models tab to download one."
        )
        self._no_models_hint.setWordWrap(True)
        self._no_models_hint.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" font-style: italic; background: transparent;"
        )
        form.addRow("", self._no_models_hint)

        self._saved_model = settings.get("stt_model", "")

        # Hotkey / Language
        self.hotkey = HotkeyButton()
        self.hotkey.set_value(settings.get("stt_hotkey", "<ctrl>+<shift>+h"))
        form.addRow("Hotkey", self.hotkey)

        self.language = QComboBox()
        for label, _value in STT_LANGUAGES:
            self.language.addItem(label)
        current_lang = settings.get("stt_language", "")
        for i, (_, val) in enumerate(STT_LANGUAGES):
            if val == current_lang:
                self.language.setCurrentIndex(i)
                break
        form.addRow("Language", self.language)

        # Translate to English (Whisper only)
        self.translate = QCheckBox("Translate to English (Whisper only)")
        self.translate.setChecked(bool(settings.get("stt_translate", False)))
        form.addRow("", self.translate)

        layout.addLayout(form)

        hint = QLabel("Click the button above, then press your desired key combination.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(hint)

        layout.addStretch()

        # Populate model combo and wire provider switch
        self.refresh_model_combo()
        self.stt_provider.currentIndexChanged.connect(self._on_stt_provider_changed)
        self._model_combo.currentIndexChanged.connect(self._update_translate_visibility)
        self._on_stt_provider_changed(self.stt_provider.currentIndex())

    def _on_stt_provider_changed(self, index: int) -> None:
        is_openai = STT_PROVIDERS[index][1] == "openai"
        self._openai_key_label.setVisible(is_openai)
        self.openai_api_key.setVisible(is_openai)
        self._model_label.setVisible(not is_openai)
        self._model_combo.setVisible(not is_openai)
        self._no_models_hint.setVisible(not is_openai and self._model_combo.count() == 0)
        self._update_translate_visibility()

    def _update_translate_visibility(self) -> None:
        is_local = STT_PROVIDERS[self.stt_provider.currentIndex()][1] == "local"
        model_id = self._model_combo.currentData() or ""
        is_whisper = model_id.startswith("whisper")
        self.translate.setVisible(is_local and is_whisper)

    def selected_model_id(self) -> str:
        """Return the model ID selected in the combo box."""
        return self._model_combo.currentData() or ""

    def refresh_model_combo(self) -> None:
        """Rebuild the model combo with currently downloaded models."""
        from roomkit_ui.model_manager import STT_MODELS, is_model_downloaded

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for m in STT_MODELS:
            if is_model_downloaded(m.id):
                self._model_combo.addItem(f"{m.name} ({m.type})", m.id)

        # Restore previous selection
        target = self._saved_model or self._model_combo.itemData(0)
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == target:
                self._model_combo.setCurrentIndex(i)
                break
        self._model_combo.blockSignals(False)

        has_models = self._model_combo.count() > 0
        is_local = STT_PROVIDERS[self.stt_provider.currentIndex()][1] == "local"
        self._no_models_hint.setVisible(is_local and not has_models)

    def get_settings(self) -> dict:
        """Return this page's settings slice."""
        return {
            "stt_enabled": self.enabled.isChecked(),
            "stt_hotkey": self.hotkey.value(),
            "stt_provider": STT_PROVIDERS[self.stt_provider.currentIndex()][1],
            "stt_model": self.selected_model_id(),
            "stt_language": STT_LANGUAGES[self.language.currentIndex()][1],
            "stt_translate": self.translate.isChecked(),
            "_dict_openai_key": self.openai_api_key.text().strip(),
        }
