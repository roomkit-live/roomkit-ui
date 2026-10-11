"""Voice Channel fields for Meta's Muse Voice Transcribe (STT)."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget


class MetaSTTFields:
    """Meta rows of the STT page, shown for its provider only."""

    def __init__(self, settings: dict) -> None:
        self._settings = settings

    def add_stt_rows(self, form: QFormLayout) -> None:
        s = self._settings
        self.api_key = QLineEdit(s.get("meta_api_key", ""))
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("Enter your Meta API key")
        self.keywords = QLineEdit(s.get("meta_stt_keywords", ""))
        self.keywords.setPlaceholderText("RoomKit, Tremblay (optional)")
        self.keywords.setToolTip(
            "Comma-separated names and terms Muse should expect: product names, "
            "people, places. A bias, not a guaranteed spelling."
        )
        rows: list[QWidget] = []
        for label_text, field in (("Meta Key", self.api_key), ("Keywords", self.keywords)):
            label = QLabel(label_text)
            form.addRow(label, field)
            rows += [label, field]
        self._rows = tuple(rows)

    def update_stt_visibility(self, provider: str) -> None:
        for widget in self._rows:
            widget.setVisible(provider == "meta")

    def get_settings(self) -> dict:
        return {
            "meta_api_key": self.api_key.text().strip(),
            "meta_stt_keywords": self.keywords.text().strip(),
        }
