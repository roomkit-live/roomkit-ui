"""Voice Channel fields for Meta's Muse Voice Transcribe (STT)."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit


class MetaSTTFields:
    """Meta rows of the STT page, shown for its provider only."""

    def __init__(self, settings: dict) -> None:
        self._settings = settings

    def add_stt_rows(self, form: QFormLayout) -> None:
        s = self._settings
        self.keywords = QLineEdit(s.get("meta_stt_keywords", ""))
        self.keywords.setPlaceholderText("RoomKit, Tremblay (optional)")
        self.keywords.setToolTip(
            "Comma-separated names and terms Muse should expect: product names, "
            "people, places. A bias, not a guaranteed spelling."
        )
        self._label = QLabel("Keywords")
        form.addRow(self._label, self.keywords)

    def update_stt_visibility(self, provider: str) -> None:
        self._label.setVisible(provider == "meta")
        self.keywords.setVisible(provider == "meta")

    def get_settings(self) -> dict:
        return {
            "meta_stt_keywords": self.keywords.text().strip(),
        }
