"""Dictation log window — shows real-time STT events for debugging."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class DictationLog(QWidget):
    """Floating window that displays dictation events."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dictation Log")
        self.setMinimumSize(480, 300)
        self.resize(520, 360)
        self.setWindowFlags(Qt.Window)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            "QTextEdit {"
            "  font-family: monospace; font-size: 12px;"
            "  background-color: #1C1C1E; color: #E5E5EA;"
            "  border: 1px solid #2C2C2E; border-radius: 6px;"
            "  padding: 6px;"
            "}"
        )
        layout.addWidget(self._log, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._log.clear)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

    def _append(self, tag: str, color: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.append(
            f'<span style="color:#636366">{ts}</span> '
            f'<span style="color:{color}; font-weight:600">[{tag}]</span> '
            f"{message}"
        )

    @Slot(bool)
    def on_recording_changed(self, recording: bool) -> None:
        if recording:
            self._append("REC", "#FF453A", "Recording started")
        else:
            self._append("REC", "#FF9F0A", "Recording stopped")

    @Slot(str)
    def on_text_ready(self, text: str) -> None:
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._append("STT", "#30D158", escaped)

    @Slot(str)
    def on_error(self, message: str) -> None:
        escaped = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._append("ERR", "#FF453A", escaped)
