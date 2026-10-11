"""An in-layout loading page; session controls remain available beneath it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from roomkit_ui.theme_live import themed_style


class SessionLoading(QWidget):
    """Keep startup progress in the conversation area, without an overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stopping = False
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        layout.addStretch()
        title = QLabel("Getting ready")
        title.setAlignment(Qt.AlignCenter)
        themed_style(
            title,
            lambda c: (
                f"color: {c['TEXT_PRIMARY']}; font-size: 26px; font-weight: 500;"
                " background: transparent;"
            ),
        )
        layout.addWidget(title)
        self._status = QLabel()
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        themed_style(
            self._status,
            lambda c: f"color: {c['TEXT_SECONDARY']}; font-size: 14px; background: transparent;",
        )
        layout.addWidget(self._status)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedSize(144, 3)
        self._progress.setAccessibleName("Preparing the conversation")
        themed_style(
            self._progress,
            lambda c: (
                "QProgressBar {"
                f" background: {c['BG_TERTIARY']}; border: none; border-radius: 1px; }}"
                f"QProgressBar::chunk {{ background: {c['ACCENT_BRAND']}; border-radius: 1px; }}"
            ),
        )
        layout.addWidget(self._progress, 0, Qt.AlignHCenter)
        layout.addStretch()
        self.set_status("")

    def start(self) -> None:
        self._stopping = False
        self._progress.show()
        self.set_status("")

    def stop(self) -> None:
        self._stopping = True
        self._progress.hide()
        self._status.setText("Closing the connection…")

    def set_status(self, message: str) -> None:
        # Backend steps are useful in logs. Here only distinguish a local
        # model's longer startup from the ordinary connection handshake.
        if self._stopping:
            return
        model_loading = any(
            word in message.lower()
            for word in ("model", "stt", "tts", "llama.cpp", "turn detector")
        )
        self._status.setText(
            "Preparing your models…" if model_loading else "Connecting your conversation…"
        )
