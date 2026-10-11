"""A quiet Live header with session details available on demand."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.icons import svg_icon
from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme, themed_style
from roomkit_ui.widgets.buttons import KeyboardButton

# Vendor-cased display names; .capitalize() fallback for anything unlisted.
_PROVIDER_NAMES = {
    "gemini": "Gemini",
    "openai": "OpenAI",
    "deepgram": "Deepgram",
    "elevenlabs": "ElevenLabs",
    "xai": "xAI Grok",
    "anthropic": "Anthropic",
    "openai_live": "OpenAI GPT-Live",
    "llamacpp": "llama.cpp",
}


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _usage_summary(payload: dict) -> str:
    """Header fragment like ``"$0.0123 · 4.2k tok"`` from a usage payload.

    ``cost_usd`` is None when no catalog pricing exists for the model
    (local/unknown) — then only the token count is shown.
    """
    tokens = int(payload.get("input_tokens") or 0) + int(payload.get("output_tokens") or 0)
    parts = []
    cost = payload.get("cost_usd")
    if cost is not None:
        parts.append(f"${cost:.2f}" if cost >= 1 else f"${cost:.4f}")
    if tokens:
        parts.append(f"{_format_tokens(tokens)} tok")
    return " · ".join(parts)


class SessionInfoBar(QWidget):
    """RoomKit identity stays visible; model, tools and usage stay one tap away."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("SessionInfoBar { background: transparent; }")
        self._provider_display = ""
        self._model_display = ""
        self._tools_display = ""
        self._skills_display = ""
        self._attitude_display = ""
        self._cost_display = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 4)
        outer.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(10)
        mark = QLabel()
        logo = Path(__file__).resolve().parent.parent / "assets" / "logo.svg"
        mark.setPixmap(QIcon(str(logo)).pixmap(QSize(26, 26), self.devicePixelRatioF()))
        mark.setFixedSize(26, 26)
        mark.setStyleSheet("background: transparent;")
        header.addWidget(mark)
        name = QLabel("roomkit.")
        themed_style(
            name,
            lambda c: (
                f"color: {c['TEXT_PRIMARY']}; font-size: 18px; font-weight: 600;"
                " background: transparent;"
            ),
        )
        header.addWidget(name)
        header.addStretch()
        self._toggle_button = KeyboardButton()
        self._toggle_button.setCheckable(True)
        self._toggle_button.setFixedSize(40, 40)
        self._toggle_button.setIconSize(QSize(20, 20))
        self._toggle_button.setCursor(Qt.PointingHandCursor)
        self._toggle_button.setAccessibleName("Session details")
        self._toggle_button.setToolTip("Session details")
        themed_style(
            self._toggle_button,
            lambda c: (
                "QPushButton { background: transparent; border: 1px solid transparent;"
                " border-radius: 14px; padding: 0; }"
                f"QPushButton:hover, QPushButton:checked {{ background: {c['BG_SECONDARY']}; }}"
                'QPushButton[keyboardFocus="true"] {'
                f" border-color: {c['ACCENT_BRAND']}; }}"
            ),
        )
        self._toggle_button.toggled.connect(self._set_expanded)
        bind_theme(self, self._refresh_icon)
        header.addWidget(self._toggle_button)
        outer.addLayout(header)

        self._detail_area = QScrollArea()
        self._detail_area.setWidgetResizable(True)
        self._detail_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._detail_area.setFrameShape(QFrame.NoFrame)
        self._detail_area.setStyleSheet("background: transparent;")
        self._detail_container = QFrame()
        self._detail_container.setObjectName("sessionDetails")
        themed_style(
            self._detail_container,
            lambda c: (
                "QFrame#sessionDetails {"
                f" background: {c['BG_SECONDARY']}; border-radius: 16px; }}"
            ),
        )
        details = QVBoxLayout(self._detail_container)
        details.setContentsMargins(16, 14, 16, 14)
        details.setSpacing(10)
        self._summary_label = QLabel()
        self._summary_label.setTextFormat(Qt.PlainText)
        self._summary_label.setWordWrap(True)
        themed_style(
            self._summary_label,
            lambda c: f"color: {c['TEXT_PRIMARY']}; font-size: 13px; background: transparent;",
        )
        details.addWidget(self._summary_label)
        self._detail_layout = QVBoxLayout()
        self._detail_layout.setSpacing(10)
        details.addLayout(self._detail_layout)
        self._detail_area.setWidget(self._detail_container)
        self._detail_area.hide()
        outer.addWidget(self._detail_area)
        self.hide()

    def _refresh_icon(self) -> None:
        self._toggle_button.setIcon(svg_icon("information-circle", colors()["TEXT_SECONDARY"], 20))

    def set_session(self, info: dict) -> None:
        provider = info.get("provider", "")
        tools: list[dict] = info.get("tools", [])
        skills: list[dict] = info.get("skills", [])
        failed: list[str] = info.get("failed_servers", [])
        self._provider_display = _PROVIDER_NAMES.get(provider, provider.capitalize())
        self._model_display = info.get("model", "")
        self._tools_display = f"{len(tools)} {'tool' if len(tools) == 1 else 'tools'}"
        self._skills_display = f"{len(skills)} {'skill' if len(skills) == 1 else 'skills'}"
        self._attitude_display = self._cost_display = ""
        self._rebuild_summary()
        self._clear_details()
        if failed:
            label = QLabel(f"Unavailable integrations: {', '.join(failed)}")
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            themed_style(
                label,
                lambda c: f"color: {c['ACCENT_RED']}; font-size: 12px; background: transparent;",
            )
            self._detail_layout.addWidget(label)
        for icon, entries in (("⚙", tools), ("✦", skills), ("◇", info.get("agent", []))):
            for entry in entries:
                self._add_detail_row(icon, entry.get("name", ""), entry.get("description", ""))
        self._toggle_button.setChecked(False)
        self._set_expanded(False)
        self.show()

    def _add_detail_row(self, icon: str, name: str, description: str) -> None:
        row = QLabel(f"<b>{icon} {_esc(name)}</b><br>{_esc(description)}")
        row.setTextFormat(Qt.RichText)
        row.setWordWrap(True)
        themed_style(
            row,
            lambda c: f"color: {c['TEXT_SECONDARY']}; font-size: 12px; background: transparent;",
        )
        self._detail_layout.addWidget(row)

    def set_attitude(self, description: str) -> None:
        self._attitude_display = description
        self._rebuild_summary()

    def update_cost(self, payload: dict) -> None:
        self._cost_display = _usage_summary(payload)
        self._rebuild_summary()

    def clear_session(self) -> None:
        self._toggle_button.setChecked(False)
        self._set_expanded(False)
        self._provider_display = self._model_display = ""
        self._tools_display = self._skills_display = ""
        self._attitude_display = self._cost_display = ""
        self._summary_label.clear()
        self._clear_details()
        self.hide()

    def _rebuild_summary(self) -> None:
        parts = [self._provider_display, self._model_display]
        inventory = " · ".join(filter(None, (self._tools_display, self._skills_display)))
        parts.extend((inventory, self._attitude_display, self._cost_display))
        self._summary_label.setText("\n".join(filter(None, parts)))

    def _set_expanded(self, expanded: bool) -> None:
        self._detail_area.setVisible(expanded)
        self._detail_area.setFixedHeight(220)
        name = "Hide session details" if expanded else "Session details"
        self._toggle_button.setAccessibleName(name)
        self._toggle_button.setToolTip(name)

    def _clear_details(self) -> None:
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            if item is not None and (widget := item.widget()) is not None:
                widget.deleteLater()


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
