"""A quiet Live header with session details available on demand."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)

from roomkit_ui.icons import svg_icon
from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme, themed_style
from roomkit_ui.widgets.buttons import KeyboardButton


class SessionInfoBar(QWidget):
    """Conversation navigation and session details, without extra branding."""

    history_requested = Signal()
    details_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("SessionInfoBar { background: transparent; }")
        header = QHBoxLayout(self)
        header.setContentsMargins(20, 12, 20, 4)
        header.setSpacing(10)
        self._history = KeyboardButton()
        self._history.setFixedSize(40, 40)
        self._history.setIconSize(QSize(20, 20))
        self._history.setAccessibleName("Conversations")
        self._history.setToolTip("Conversations")
        self._history.setCursor(Qt.PointingHandCursor)
        self._history.clicked.connect(self.history_requested.emit)
        themed_style(
            self._history,
            lambda c: (
                "QPushButton { background: transparent; border: 1px solid transparent;"
                " border-radius: 12px; padding: 0; }"
                f"QPushButton:hover {{ background: {c['BG_SECONDARY']}; }}"
                'QPushButton[keyboardFocus="true"] {'
                f" border-color: {c['ACCENT_BRAND']}; }}"
            ),
        )
        header.addWidget(self._history)

        header.addStretch()
        self._details_button = KeyboardButton()
        self._details_button.setFixedSize(40, 40)
        self._details_button.setIconSize(QSize(20, 20))
        self._details_button.setCursor(Qt.PointingHandCursor)
        self._details_button.setAccessibleName("Session details")
        self._details_button.setToolTip("Session details")
        themed_style(
            self._details_button,
            lambda c: (
                "QPushButton { background: transparent; border: 1px solid transparent;"
                " border-radius: 14px; padding: 0; }"
                f"QPushButton:hover {{ background: {c['BG_SECONDARY']}; }}"
                'QPushButton[keyboardFocus="true"] {'
                f" border-color: {c['ACCENT_BRAND']}; }}"
            ),
        )
        self._details_button.clicked.connect(self.details_requested.emit)
        bind_theme(self, self._refresh_icon)
        header.addWidget(self._details_button)
        self.hide()

    def _refresh_icon(self) -> None:
        self._history.setIcon(svg_icon("sidebar", colors()["TEXT_SECONDARY"], 20))
        self._details_button.setIcon(
            svg_icon("information-circle", colors()["TEXT_SECONDARY"], 20)
        )
