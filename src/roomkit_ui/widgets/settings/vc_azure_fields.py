"""Azure speech model, endpoint and voice settings; credentials live in Providers."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget


def _set_visible(visible: bool, widgets: tuple[QWidget, ...]) -> None:
    for widget in widgets:
        widget.setVisible(visible)


class AzureSpeechFields:
    """Azure rows of the STT and TTS pages, shown for their provider only."""

    def __init__(self, settings: dict) -> None:
        self._settings = settings

    def add_stt_rows(self, form: QFormLayout) -> None:
        s = self._settings
        self.endpoint = QLineEdit(s.get("azure_mai_endpoint", ""))
        self.endpoint.setPlaceholderText("https://<resource>.services.ai.azure.com")
        self.deployment = QLineEdit(s.get("azure_mai_deployment", ""))
        self.deployment.setPlaceholderText("MAI-Transcribe-2-Streaming")
        self._stt_rows = self._add_rows(
            form, [("Endpoint", self.endpoint), ("Deployment", self.deployment)]
        )

    def add_tts_rows(self, form: QFormLayout) -> None:
        s = self._settings
        self.region = QLineEdit(s.get("azure_speech_region", ""))
        self.region.setPlaceholderText("e.g. swedencentral")
        self.voice = QLineEdit(s.get("azure_tts_voice", ""))
        self.voice.setPlaceholderText("en-US-Harper:MAI-Voice-2.1-Flash")
        self.voice.setToolTip(
            "Voice name as Azure spells it: fr-FR-Soleil:MAI-Voice-2.1-Flash speaks "
            "French; a …Neural name is one of Azure's neural voices."
        )
        self.rate = QLineEdit(s.get("azure_tts_rate", ""))
        self.rate.setPlaceholderText("+15%, 1.2 or fast (empty = the voice's own)")
        self._tts_rows = self._add_rows(
            form, [("Region", self.region), ("Voice", self.voice), ("Rate", self.rate)]
        )

    @staticmethod
    def _add_rows(form: QFormLayout, rows: list[tuple[str, QLineEdit]]) -> tuple[QWidget, ...]:
        widgets: list[QWidget] = []
        for label_text, field in rows:
            label = QLabel(label_text)
            form.addRow(label, field)
            widgets += [label, field]
        return tuple(widgets)

    def update_stt_visibility(self, provider: str) -> None:
        _set_visible(provider == "azure_mai", self._stt_rows)

    def update_tts_visibility(self, provider: str) -> None:
        _set_visible(provider == "azure", self._tts_rows)

    def get_settings(self) -> dict:
        return {
            "azure_mai_endpoint": self.endpoint.text().strip(),
            "azure_mai_deployment": self.deployment.text().strip(),
            "azure_speech_region": self.region.text().strip(),
            "azure_tts_voice": self.voice.text().strip(),
            "azure_tts_rate": self.rate.text().strip(),
        }
