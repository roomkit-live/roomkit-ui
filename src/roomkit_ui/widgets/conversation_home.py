"""Compact native welcome and navigation for the voice conversation."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPaintEvent, QRadialGradient
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from roomkit_ui.icons import svg_icon
from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme, themed_style
from roomkit_ui.widgets.buttons import KeyboardButton


class ConversationSurface(QWidget):
    """One violet background shared by home, loading and conversation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("conversationSurface")
        self.setStyleSheet("QWidget#conversationSurface { background: transparent; }")
        bind_theme(self, self.update)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        c = colors()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(c["BG_PRIMARY"]))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        # Overlapping ellipses fade out before the navigation. The lower
        # edge carries the color, leaving the welcome copy easy to read.
        for x, y, rx, ry, color, alpha in (
            (0.15, 1.04, 1.18, 0.64, "#6366F1", 46),
            (0.94, 0.86, 1.08, 0.59, c["ACCENT_BRAND"], 62),
        ):
            painter.save()
            painter.translate(self.width() * x, self.height() * y)
            painter.scale(self.width() * rx, self.height() * ry)
            gradient = QRadialGradient(QPointF(0, 0), 1)
            tint = QColor(color)
            tint.setAlpha(alpha)
            gradient.setColorAt(0, tint)
            tint.setAlpha(alpha // 2)
            gradient.setColorAt(0.5, tint)
            tint.setAlpha(0)
            gradient.setColorAt(1, tint)
            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(0, 0), 1, 1)
            painter.restore()
        painter.end()


class ConversationHeader(QWidget):
    """Keep navigation within reach without taking space from the conversation."""

    history_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("ConversationHeader { background: transparent; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 12, 16, 8)
        layout.setSpacing(4)
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
        layout.addWidget(self._history)
        self._title = QLabel()
        self._title.setTextFormat(Qt.PlainText)
        themed_style(
            self._title,
            lambda c: f"color: {c['TEXT_PRIMARY']}; font-size: 14px; background: transparent;",
        )
        layout.addWidget(self._title, 1)
        layout.addStretch()

        bind_theme(self, self._refresh_icon)

    def _refresh_icon(self) -> None:
        self._history.setIcon(svg_icon("sidebar", colors()["TEXT_SECONDARY"], 20))

    def set_conversation(self, title: str) -> None:
        self._title.setText(self._title.fontMetrics().elidedText(title, Qt.ElideRight, 310))
        self._title.setToolTip(title)


class ConversationWelcome(QWidget):
    """A single invitation, sized for the app's narrow portrait window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 36)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignCenter)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        brand.addStretch()
        mark = QLabel()
        mark.setFixedSize(44, 44)
        mark.setAlignment(Qt.AlignCenter)
        logo = Path(__file__).resolve().parent.parent / "assets" / "logo.svg"
        # QIcon renders the SVG at the display's pixel ratio, including Retina.
        mark.setPixmap(QIcon(str(logo)).pixmap(QSize(44, 44), self.devicePixelRatioF()))
        brand.addWidget(mark)
        wordmark = QLabel("roomkit.")
        themed_style(
            wordmark,
            lambda c: (
                f"font-size: 26px; font-weight: 600; color: {c['TEXT_PRIMARY']};"
                " background: transparent;"
            ),
        )
        brand.addWidget(wordmark)
        brand.addStretch()
        layout.addLayout(brand)
        layout.addSpacing(24)

        title = QLabel("Where should\nwe start?")
        title.setAlignment(Qt.AlignCenter)
        themed_style(
            title,
            lambda c: (
                f"font-size: 32px; font-weight: 600; color: {c['TEXT_PRIMARY']};"
                " background: transparent;"
            ),
        )
        layout.addWidget(title)
        layout.addSpacing(16)

        hint = QLabel("A question, an idea, a little help.\nLet’s talk it through.")
        hint.setAlignment(Qt.AlignCenter)
        themed_style(
            hint,
            lambda c: f"font-size: 14px; color: {c['TEXT_SECONDARY']}; background: transparent;",
        )
        layout.addWidget(hint)


class LiveWelcome(QWidget):
    """A calm invitation until the first spoken turn arrives."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        title = QLabel("What's on your mind?")
        title.setAlignment(Qt.AlignCenter)
        themed_style(
            title,
            lambda c: (
                f"color: {c['TEXT_PRIMARY']}; font-size: 26px; font-weight: 500;"
                " background: transparent;"
            ),
        )
        layout.addWidget(title)
