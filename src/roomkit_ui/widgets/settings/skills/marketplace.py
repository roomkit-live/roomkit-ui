"""skills.sh marketplace tab."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from roomkit_ui.theme import colors

SKILLS_SH_URL = "https://skills.sh"


class MarketplaceTab(QWidget):
    """Self-contained skills.sh marketplace tab content."""

    def __init__(self, *, on_installed=None, parent=None) -> None:
        super().__init__(parent)
        self._loaded = False
        self._cb_installed = on_installed

        c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)

        title = QLabel("skills.sh")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {c['TEXT_PRIMARY']};"
            " background: transparent;"
        )
        layout.addWidget(title)

        desc = QLabel(
            "Browse the public skills catalog in your browser, then add the selected "
            "GitHub repository as a Git source from My Skills."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        cli = QLabel("CLI: npx skills add owner/repo")
        cli.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cli.setStyleSheet(
            f"font-size: 12px; font-family: monospace; color: {c['TEXT_PRIMARY']};"
            f" background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            " border-radius: 6px; padding: 8px 10px;"
        )
        layout.addWidget(cli)

        open_btn = QPushButton("Open skills.sh")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setFixedHeight(30)
        open_btn.setStyleSheet(
            f"QPushButton {{ font-size: 12px; font-weight: 600;"
            f" background: {c['ACCENT_BLUE']}; color: #FFFFFF;"
            " border: none; border-radius: 6px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {c['ACCENT_BLUE']}; }}"
        )
        open_btn.clicked.connect(self._open_marketplace)
        layout.addWidget(open_btn, 0, Qt.AlignLeft)
        layout.addStretch(1)

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Mark the external marketplace tab as loaded."""
        self._loaded = True

    def _open_marketplace(self) -> None:
        QDesktopServices.openUrl(QUrl(SKILLS_SH_URL))
