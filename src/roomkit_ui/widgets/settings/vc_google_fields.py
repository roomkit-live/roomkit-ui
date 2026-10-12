"""Voice Channel fields for Google Gemini STT and TTS; the key lives in Providers."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QWidget

from roomkit_ui.tts.gemini import DEFAULT_MODEL, DEFAULT_VOICE
from roomkit_ui.widgets.settings.realtime_catalogs import (
    GEMINI_VOICES,
    populate_model_combo,
    populate_voice_combo,
    voice_options,
)


def _tts_models() -> list[str]:
    """roomkit's Gemini TTS models, the voice-agent one first."""
    try:
        from roomkit.voice.tts.gemini import GEMINI_TTS_MODELS
    except Exception:
        return [DEFAULT_MODEL]
    return [DEFAULT_MODEL, *(model for model in GEMINI_TTS_MODELS if model != DEFAULT_MODEL)]


def _set_visible(visible: bool, widgets: tuple[QWidget, ...]) -> None:
    for widget in widgets:
        widget.setVisible(visible)


class GeminiSpeechFields:
    """Gemini rows of the STT and TTS pages, shown for their provider only."""

    def __init__(self, settings: dict) -> None:
        self._settings = settings

    def add_stt_rows(self, form: QFormLayout) -> None:
        self.vocabulary = QLineEdit(self._settings.get("gemini_stt_vocabulary", ""))
        self.vocabulary.setPlaceholderText("RoomKit, Tremblay (optional)")
        self.vocabulary.setToolTip(
            "Comma-separated names and terms the recogniser gets wrong: product names, "
            "people, places. Google reports the best results under about 100."
        )
        label = QLabel("Vocabulary")
        form.addRow(label, self.vocabulary)
        self._stt_rows: tuple[QWidget, ...] = (label, self.vocabulary)

    def add_tts_rows(self, form: QFormLayout) -> None:
        s = self._settings
        self.model = QComboBox()
        populate_model_combo(
            self.model, _tts_models(), s.get("gemini_tts_model", "") or DEFAULT_MODEL
        )
        self.model.setToolTip(
            "Flash Lite is built for voice agents and starts speaking sooner; "
            "3.8 Flash has more acting range, about half a second later."
        )
        self.voice = QComboBox()
        self.voice.setEditable(True)
        populate_voice_combo(
            self.voice,
            voice_options("roomkit.providers.gemini.voices", GEMINI_VOICES),
            s.get("gemini_tts_voice", "") or DEFAULT_VOICE,
        )
        self.voice.setToolTip("A prebuilt voice, or any voice id from Google's catalog.")
        self.style = QLineEdit(s.get("gemini_tts_style", ""))
        self.style.setPlaceholderText("warm and calm (optional)")
        self.style.setToolTip(
            "How every reply is delivered, in plain words. The model performs it, "
            "it does not read it."
        )
        rows: list[QWidget] = []
        for text, field in (("Model", self.model), ("Voice", self.voice), ("Style", self.style)):
            label = QLabel(text)
            form.addRow(label, field)
            rows += [label, field]
        self._tts_rows: tuple[QWidget, ...] = tuple(rows)

    def update_stt_visibility(self, provider: str) -> None:
        _set_visible(provider == "gemini", self._stt_rows)

    def update_tts_visibility(self, provider: str) -> None:
        _set_visible(provider == "gemini", self._tts_rows)

    def get_settings(self) -> dict:
        return {
            "gemini_stt_vocabulary": self.vocabulary.text().strip(),
            "gemini_tts_model": self.model.currentText().strip(),
            # Editable: the text is the id, picked or typed.
            "gemini_tts_voice": self.voice.currentText().strip(),
            "gemini_tts_style": self.style.text().strip(),
        }
