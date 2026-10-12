"""Shared RoomKit wordmark for native navigation panels."""

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class NavigationBrand(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        mark = QLabel()
        mark.setFixedSize(34, 34)
        asset = Path(__file__).resolve().parents[1] / "assets" / "logo.svg"
        mark.setPixmap(QIcon(str(asset)).pixmap(34, 34))
        layout.addWidget(mark)
        wordmark = QLabel("roomkit.")
        wordmark.setStyleSheet("font-size: 25px; font-weight: 600; letter-spacing: -1px;")
        layout.addWidget(wordmark)
        layout.addStretch()
