"""Single iMessage-style chat bubble with timestamp."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


class ChatBubble(QFrame):
    """A rounded chat bubble — blue/right for user, gray/left for AI."""

    def __init__(
        self,
        text: str,
        role: str = "assistant",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._role = role
        self._finalized = False
        self._created = datetime.now()

        is_user = role == "user"

        # ── Bubble container ──
        self._bubble = QFrame()
        self._bubble.setObjectName("bubbleFrame")
        bg = "#0A84FF" if is_user else "#2C2C2E"
        self._bubble.setStyleSheet(
            f"QFrame#bubbleFrame {{"
            f"  background-color: {bg};"
            f"  border-radius: 18px;"
            f"  border-top-{'right' if is_user else 'left'}-radius: 4px;"
            f"}}"
        )

        # ── Message text ──
        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.PlainText)
        self._label.setMaximumWidth(270)
        self._label.setStyleSheet(
            "QLabel {"
            "  color: #FFFFFF;"
            "  font-size: 13px;"
            "  line-height: 1.4;"
            "  padding: 10px 14px 8px 14px;"
            "  background: transparent;"
            "}"
        )

        bubble_layout = QVBoxLayout(self._bubble)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(0)
        bubble_layout.addWidget(self._label)

        # ── Timestamp ──
        self._time_label = QLabel(self._created.strftime("%H:%M"))
        align = Qt.AlignRight if is_user else Qt.AlignLeft
        self._time_label.setAlignment(align)
        self._time_label.setStyleSheet(
            "QLabel {"
            "  color: #636366;"
            "  font-size: 10px;"
            "  background: transparent;"
            "  padding: 2px 4px 0px 4px;"
            "}"
        )

        # ── Row: bubble aligned left or right ──
        row = QHBoxLayout()
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(0)
        if is_user:
            row.addStretch()
            row.addWidget(self._bubble)
        else:
            row.addWidget(self._bubble)
            row.addStretch()

        # ── Time row ──
        time_row = QHBoxLayout()
        time_row.setContentsMargins(14, 0, 14, 0)
        if is_user:
            time_row.addStretch()
            time_row.addWidget(self._time_label)
        else:
            time_row.addWidget(self._time_label)
            time_row.addStretch()

        # ── Outer layout ──
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 1)
        outer.setSpacing(0)
        outer.addLayout(row)
        outer.addLayout(time_row)
        self.setStyleSheet("background: transparent;")

    @property
    def role(self) -> str:
        return self._role

    @property
    def finalized(self) -> bool:
        return self._finalized

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def append_text(self, text: str) -> None:
        self._label.setText(self._label.text() + text)

    def text(self) -> str:
        return self._label.text()

    def finalize(self) -> None:
        self._finalized = True
        # Update timestamp to finalization time
        self._time_label.setText(datetime.now().strftime("%H:%M"))
