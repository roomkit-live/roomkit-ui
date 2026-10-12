"""Dictation activation, shortcut and transcription preferences."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QWidget

from roomkit_ui.constants import DICTATION_LANGUAGES, STT_PROVIDERS
from roomkit_ui.widgets.hotkey_button import HotkeyButton
from roomkit_ui.widgets.install_offer import InstallOffer
from roomkit_ui.widgets.settings.controls import (
    FeedbackLabel,
    SettingRow,
    SettingsForm,
    SettingsSection,
    SettingsToggle,
    label,
    navigation_link,
    page_layout,
)
from roomkit_ui.widgets.settings.feature_hints import (
    offer_install,
    populate_provider_combo,
    refresh_provider_combo,
)

_PROVIDER_FEATURES = {
    "openai": "openai-realtime",
    "deepgram": "deepgram",
    "local": "local-voice",
}


class _DictationPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = page_layout(
            self,
            "Dictation",
            "Dictate into a message, or use a shortcut to paste into another app.",
        )
        activation = SettingsSection("Activation & shortcut")
        self.enabled = SettingsToggle(
            "Enable global shortcut", bool(settings.get("stt_enabled", True))
        )
        activation.add_row(
            "Enable global shortcut",
            "Use a global shortcut to start and stop recording.",
            self.enabled,
        )
        self.hotkey = HotkeyButton()
        self.hotkey.setAutoDefault(False)
        self.hotkey.setMinimumWidth(140)
        self.hotkey.set_value(settings.get("stt_hotkey", "<ctrl>+<shift>+h"))
        self.hotkey.setEnabled(self.enabled.isChecked())
        self.enabled.toggled.connect(self.hotkey.setEnabled)
        activation.add_row(
            "Dictation shortcut",
            "Click the keys, then press a new shortcut. Escape cancels recording.",
            self.hotkey,
        )
        self.hotkey_offer = InstallOffer("hotkey")
        activation.content.addWidget(self.hotkey_offer)
        layout.addWidget(activation)

        transcription = SettingsSection("Transcription", "Choose how your speech becomes text.")
        transcription.content.setContentsMargins(18, 16, 18, 16)
        transcription.content.setSpacing(12)
        form = SettingsForm()
        self.stt_provider = QComboBox()
        populate_provider_combo(self.stt_provider, STT_PROVIDERS, _PROVIDER_FEATURES)
        current = settings.get("stt_provider", "openai")
        self.stt_provider.setCurrentIndex(
            next((i for i, (_, value) in enumerate(STT_PROVIDERS) if value == current), 0)
        )
        form.addRow("Speech recognition provider", self.stt_provider)
        self.provider_offer = offer_install(self.stt_provider, STT_PROVIDERS, _PROVIDER_FEATURES)
        form.addRow(self.provider_offer)
        self._provider_hint = label("", "settingsHint")
        form.addRow(self._provider_hint)
        self.providers_link = navigation_link("Manage providers & keys →")
        self.providers_link.clicked.connect(lambda: self.navigate_requested.emit("providers"))
        form.addRow(self.providers_link)

        self._saved_model = settings.get("stt_model", "")
        self._model_combo = QComboBox()
        self._model_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._model_combo.setMinimumContentsLength(18)
        self._model_label = label("Local model", "settingsFieldLabel")
        form.addRow(self._model_label, self._model_combo)
        self._no_models_hint = FeedbackLabel()
        form.addRow(self._no_models_hint)
        self.models_link = navigation_link("Browse local models →")
        self.models_link.clicked.connect(lambda: self.navigate_requested.emit("models"))
        form.addRow(self.models_link)

        # The spoken language is General's; dictation may set its own.
        self.language = QComboBox()
        for title, value in DICTATION_LANGUAGES:
            self.language.addItem(title, value)
        self.language.setCurrentIndex(
            max(0, self.language.findData(settings.get("dictation_language", "")))
        )
        form.addRow("Dictation language", self.language)
        self.spoken_language_link = navigation_link("Set your spoken language in General →")
        self.spoken_language_link.clicked.connect(lambda: self.navigate_requested.emit("general"))
        form.addRow(self.spoken_language_link)
        transcription.content.addLayout(form)
        self.translate = SettingsToggle(
            "Translate to English", bool(settings.get("stt_translate", False))
        )
        self._translation_row = SettingRow(
            "Translate to English",
            "Use Whisper to produce English text from your speech.",
            self.translate,
        )
        transcription.content.addWidget(self._translation_row)
        layout.addWidget(transcription)
        self.audio_link = navigation_link("Choose microphone in Audio & voice →")
        self.audio_link.clicked.connect(lambda: self.navigate_requested.emit("audio"))
        layout.addWidget(self.audio_link, 0, Qt.AlignLeft)
        layout.addStretch()

        self.stt_provider.currentIndexChanged.connect(self._update_provider)
        self._model_combo.currentIndexChanged.connect(self._update_provider)
        self.refresh_model_combo()

    def _update_provider(self) -> None:
        from roomkit_ui.model_manager import is_model_downloaded

        provider = STT_PROVIDERS[self.stt_provider.currentIndex()][1]
        local = provider == "local"
        for widget in (self._model_label, self._model_combo, self.models_link):
            widget.setVisible(local)
        self.providers_link.setVisible(not local)
        self._provider_hint.setText(
            "Speech is transcribed on this device. Choose a downloaded model below."
            if local
            else f"{STT_PROVIDERS[self.stt_provider.currentIndex()][0]} receives your audio for "
            "transcription. Its key is managed in Providers & keys."
        )
        model = self.selected_model_id()
        missing = local and (not model or not is_model_downloaded(model))
        self._no_models_hint.set_status(
            (
                "The selected model is not downloaded. Download it or choose another model."
                if model
                else "Download a speech recognition model to use local dictation."
            )
            if missing
            else "",
            "error",
        )
        self._translation_row.setVisible(local and model.startswith("whisper"))

    def selected_model_id(self) -> str:
        return self._model_combo.currentData() or ""

    def refresh_model_combo(self) -> None:
        """Keep an unavailable selection visible until the user chooses a replacement."""
        from roomkit_ui.model_manager import STT_MODELS, is_model_downloaded

        target = self._model_combo.currentData() or self._saved_model
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for model in STT_MODELS:
            if is_model_downloaded(model.id):
                self._model_combo.addItem(f"{model.name} ({model.type})", model.id)
        if target and self._model_combo.findData(target) < 0:
            name = next((model.name for model in STT_MODELS if model.id == target), target)
            self._model_combo.addItem(f"{name} — not downloaded", target)
        if target:
            self._model_combo.setCurrentIndex(self._model_combo.findData(target))
        self._model_combo.blockSignals(False)
        refresh_provider_combo(self.stt_provider, STT_PROVIDERS, _PROVIDER_FEATURES)
        self.provider_offer.set_feature(
            _PROVIDER_FEATURES[STT_PROVIDERS[self.stt_provider.currentIndex()][1]]
        )
        self.hotkey_offer.set_feature("hotkey")
        self._update_provider()

    def get_settings(self) -> dict:
        return {
            "stt_enabled": self.enabled.isChecked(),
            "stt_hotkey": self.hotkey.value(),
            "stt_provider": STT_PROVIDERS[self.stt_provider.currentIndex()][1],
            "stt_model": self.selected_model_id(),
            "dictation_language": self.language.currentData() or "",
            "stt_translate": self.translate.isChecked(),
        }
