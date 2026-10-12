"""Live session details in the same native panel as conversation navigation."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.icons import svg_icon
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.widgets.buttons import KeyboardButton
from roomkit_ui.widgets.settings.style import settings_colors
from roomkit_ui.widgets.sliding_panel import SlidingPanel
from roomkit_ui.widgets.tool_activity import tool_title

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
    "local": "Local",
    "piper": "Piper",
    "qwen3": "Qwen3-TTS",
    "neutts": "NeuTTS",
    "pocket": "Pocket TTS",
    "azure": "Azure Speech",
    "azure_mai": "Azure MAI",
    "meta": "Meta Muse",
    "gradium": "Gradium",
    "typesafe": "TypeSafe Jev",
    "open_ai": "OpenAI",
    "eleven_labs": "ElevenLabs",
    "google": "Google",
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


def _label(text: str = "", name: str = "sessionDescription") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


class _EntryButton(KeyboardButton):
    """QPushButton's native size hint ignores a layout containing wrapped labels."""

    def sizeHint(self) -> QSize:  # noqa: N802
        layout = self.layout()
        hint = layout.sizeHint() if layout is not None else super().sizeHint()
        return hint.expandedTo(QSize(0, 40))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 40)

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        layout = self.layout()
        return max(40, layout.totalHeightForWidth(width) if layout is not None else 40)


class _Entry(QFrame):
    """Names stay scannable; full provider descriptions open on demand."""

    def __init__(self, name: str, description: str, *, title: str | None = None) -> None:
        super().__init__()
        self.setObjectName("sessionEntry")
        self.query = f"{name} {title or ''} {description}".casefold()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.toggle = _EntryButton()
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.toggle.setSizePolicy(policy)
        self.toggle.setMinimumHeight(40)
        self.toggle.setObjectName("sessionEntryButton")
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName(title or name)
        self.toggle.setToolTip(name)
        self.toggle.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self.toggle)
        row.setContentsMargins(10, 9, 10, 9)
        row.setSpacing(12)
        label = _label(title or name, "sessionEntryTitle")
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        label.setTextInteractionFlags(Qt.NoTextInteraction)
        row.addWidget(label, 1)
        self.arrow = QLabel()
        self.arrow.setFixedSize(16, 16)
        self.arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.arrow)
        layout.addWidget(self.toggle)
        self.description = _label(
            description or "No description provided.", "sessionEntryDescription"
        )
        layout.addWidget(self.description)
        self.description.hide()
        self.toggle.toggled.connect(self.description.setVisible)
        self.toggle.toggled.connect(self._refresh_icon)
        bind_theme(self, self._refresh_icon)

    def _refresh_icon(self) -> None:
        icon = "chevron-down" if self.toggle.isChecked() else "chevron-right"
        self.arrow.setPixmap(svg_icon(icon, settings_colors()["muted"], 16).pixmap(16, 16))


class SessionDrawer(SlidingPanel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__("Session details", parent, from_right=True)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search tools and skills…")
        self._search.setAccessibleName("Search session tools and skills")
        self._search.setClearButtonEnabled(True)
        self._search_icon = self._search.addAction(QIcon(), QLineEdit.LeadingPosition)
        self._search_icon.triggered.connect(self._search.setFocus)
        self._search.textChanged.connect(self._filter)
        self.body.addWidget(self._search)
        self.body.addSpacing(12)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("sessionContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 4, 12)
        layout.setSpacing(12)
        self._overview = QFrame()
        self._overview.setObjectName("sessionOverview")
        summary = QVBoxLayout(self._overview)
        summary.setContentsMargins(14, 14, 14, 14)
        summary.setSpacing(6)
        self._mode = _label("Session is starting…", "sessionValue")
        summary.addWidget(self._mode)
        self._models = QVBoxLayout()
        self._models.setSpacing(12)
        summary.addLayout(self._models)
        self._attitude = _label()
        summary.addWidget(self._attitude)
        summary.addSpacing(8)
        summary.addWidget(self._section("Usage so far"))
        self._usage = _label("No usage reported yet", "sessionValue")
        summary.addWidget(self._usage)
        layout.addWidget(self._overview)
        self._unavailable = _label("", "sessionWarning")
        layout.addWidget(self._unavailable)
        self._catalogue = QVBoxLayout()
        self._catalogue.setSpacing(14)
        layout.addLayout(self._catalogue)
        self._groups: list[tuple[QWidget, list[_Entry]]] = []
        self._empty = _label("No tools or skills in this session.")
        self._empty.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self._empty)
        layout.addStretch()
        self._scroll.setWidget(content)
        self.body.addWidget(self._scroll, 1)
        footer = QFrame()
        footer.setObjectName("drawerFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 10, 0, 0)
        self._back = KeyboardButton("Back to conversation")
        self._back.setMinimumHeight(42)
        self._back.setCursor(Qt.PointingHandCursor)
        self._back.clicked.connect(self.dismiss)
        footer_layout.addWidget(self._back)
        self.body.addWidget(footer)
        bind_theme(self, self._render_theme)
        self.clear_session()

    @staticmethod
    def _section(text: str) -> QLabel:
        label = _label(text, "drawerSection")
        font = label.font()
        font.setCapitalization(QFont.AllUppercase)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        label.setFont(font)
        return label

    def set_session(self, info: dict) -> None:
        # Inventory refreshes must not close the panel or reset live usage/personality.
        self._mode.setText(
            {"voice_channel": "Voice Channel", "text": "Text conversation"}.get(
                info.get("mode", ""), "Realtime"
            )
        )
        self._clear_models()
        for model in info.get("models", []):
            row = QWidget()
            row.setObjectName("sessionModel")
            details = QVBoxLayout(row)
            details.setContentsMargins(0, 6, 0, 0)
            details.setSpacing(3)
            details.addWidget(self._section(model["role"]))
            provider = model.get("provider", "")
            name = _PROVIDER_NAMES.get(provider, provider.capitalize())
            title = " · ".join(value for value in (name, model.get("model", "")) if value)
            details.addWidget(_label(title, "sessionModelName"))
            if model.get("description"):
                details.addWidget(_label(model["description"]))
            self._models.addWidget(row)
        failed = info.get("failed_servers", [])
        self._unavailable.setText("Unavailable integrations: " + ", ".join(failed))
        self._unavailable.setVisible(bool(failed))
        expanded = {
            row.toggle.toolTip()
            for _, rows in self._groups
            for row in rows
            if row.toggle.isChecked()
        }
        self._clear_catalogue()
        for key, name in (
            ("tools", "Tools"),
            ("skills", "Skills"),
            ("agent", "Assistant behavior"),
        ):
            entries = info.get(key, [])
            if not entries:
                continue
            group = QWidget()
            group.setObjectName("sessionGroup")
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(2)
            heading = self._section(f"{name} · {len(entries)}")
            heading.setProperty("sessionGroupHeading", True)
            group_layout.addWidget(heading)
            rows = []
            for entry in entries:
                entry_name = entry.get("name", "")
                row = _Entry(
                    entry_name,
                    entry.get("description", ""),
                    title=tool_title(entry_name) if key == "tools" else None,
                )
                row.toggle.setChecked(entry_name in expanded)
                group_layout.addWidget(row)
                rows.append(row)
            self._catalogue.addWidget(group)
            self._groups.append((group, rows))
        self._filter()

    def _filter(self) -> None:
        query = self._search.text().strip().casefold()
        self._overview.setVisible(not query)
        found = 0
        for group, rows in self._groups:
            matches = 0
            for row in rows:
                match = not query or query in row.query
                row.setVisible(match)
                matches += match
            group.setVisible(bool(matches))
            found += matches
        self._empty.setText(
            "No matching tools or skills." if query else "No tools or skills in this session."
        )
        self._empty.setVisible(not found)

    def set_attitude(self, description: str) -> None:
        self._attitude.setText(f"Personality · {description}" if description else "")
        self._attitude.setVisible(bool(description))

    def update_cost(self, payload: dict) -> None:
        self._usage.setText(_usage_summary(payload) or "No usage reported yet")

    def clear_session(self) -> None:
        self.dismiss(immediate=True)
        self._clear_catalogue()
        self._search.clear()
        self._mode.setText("Session is starting…")
        self._clear_models()
        self.set_attitude("")
        self._usage.setText("No usage reported yet")
        self._unavailable.clear()
        self._unavailable.hide()
        self._scroll.verticalScrollBar().setValue(0)
        self._filter()

    def _clear_models(self) -> None:
        while self._models.count():
            item = self._models.takeAt(0)
            if item is not None and (widget := item.widget()) is not None:
                widget.hide()
                widget.deleteLater()

    def _clear_catalogue(self) -> None:
        self._groups.clear()
        while self._catalogue.count():
            item = self._catalogue.takeAt(0)
            if item is not None and (widget := item.widget()) is not None:
                widget.hide()
                widget.deleteLater()

    def _styles(self, c: dict[str, str]) -> str:
        return super()._styles(c) + (
            "QScrollArea, QWidget#sessionContent, QWidget#sessionGroup, QFrame#sessionEntry,"
            " QWidget#sessionModel"
            " { background: transparent; border: none; }"
            f"QFrame#sessionOverview {{ background: {c['soft']};"
            f" border: 1px solid {c['border']}; border-radius: 9px; }}"
            f"QLabel#sessionDescription, QLabel#sessionEntryDescription"
            f" {{ color: {c['muted']}; font-size: 12px; }}"
            "QLabel#sessionEntryDescription { padding: 4px 10px 12px; }"
            'QLabel[sessionGroupHeading="true"] { padding: 8px 10px; }'
            "QLabel#sessionValue { font-size: 14px; font-weight: 500; }"
            "QLabel#sessionModelName { font-size: 13px; }"
            "QLabel#sessionEntryTitle { font-size: 13px; font-weight: 500; }"
            "QPushButton#sessionEntryButton { padding: 0; }"
            f"QPushButton#sessionEntryButton:checked {{ background: {c['soft']}; }}"
            f"QLabel#sessionWarning {{ color: {c['warning']}; background: {c['warning_bg']};"
            " border-radius: 7px; padding: 10px; }"
        )

    def _render_theme(self) -> None:
        super()._render_theme()
        self._search_icon.setIcon(svg_icon("magnifying-glass", settings_colors()["muted"], 18))
