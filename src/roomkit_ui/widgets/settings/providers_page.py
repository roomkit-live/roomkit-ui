"""The single editor for credentials shared by conversation and dictation."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Signal
from PySide6.QtGui import QHideEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from roomkit_ui.features import FEATURES, unavailable_reason
from roomkit_ui.widgets.settings.catalog_controls import CatalogRow, mark_dividers
from roomkit_ui.widgets.settings.controls import (
    SettingsForm,
    SettingsSection,
    label,
    navigation_link,
    page_layout,
)

# Keep the existing persisted keys: changing the navigation requires no credential migration.
PROVIDERS = (
    (
        "openai_api_key",
        "OpenAI",
        "Realtime, GPT-Live, conversation, dictation and speaking decisions",
    ),
    ("api_key", "Google Gemini", "Gemini Live and conversation"),
    ("anthropic_api_key", "Anthropic", "Conversation and Deepgram agent reasoning"),
    ("deepgram_api_key", "Deepgram", "Voice Agent, transcription and dictation"),
    ("elevenlabs_api_key", "ElevenLabs", "Conversational AI and speech synthesis"),
    ("gradium_api_key", "Gradium", "Transcription and speech synthesis"),
    ("xai_api_key", "xAI", "Grok realtime conversations"),
    ("azure_speech_api_key", "Microsoft Azure", "MAI transcription and speech synthesis"),
    ("meta_api_key", "Meta", "Muse Voice transcription and speaker identification"),
    ("typesafe_api_key", "TypeSafe", "Jev speaking decisions"),
    (
        "vc_local_api_key",
        "Local server",
        "Optional authentication for an OpenAI-compatible server",
    ),
)


_SYMBOLS = ("◎", "✦", "A", "D", "Ⅱ", "G", "x", "Az", "M", "T", ">_")
_COMPONENTS = {
    "openai_api_key": ("openai", "openai-realtime"),
    "api_key": ("gemini",),
    "anthropic_api_key": ("anthropic",),
    "deepgram_api_key": ("deepgram", "deepgram-agent"),
    "elevenlabs_api_key": ("elevenlabs",),
    "gradium_api_key": ("gradium",),
    "xai_api_key": ("openai-realtime",),
    "azure_speech_api_key": ("azure-stt", "azure-tts"),
    "meta_api_key": ("meta-stt",),
    "typesafe_api_key": ("typesafe",),
    "vc_local_api_key": ("openai",),
}


class ProvidersPage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = page_layout(
            self, "Providers & keys", "One connection for every place you use a provider."
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a provider…")
        self.search.setAccessibleName("Find a provider")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.cloud = SettingsSection(
            "Cloud providers", "Keys are shared by every feature that uses the same provider."
        )
        self.local = SettingsSection("Local providers", "Run models on your own machine.")
        self.fields: dict[str, QLineEdit] = {}
        self.cards: dict[str, CatalogRow] = {}
        self.editors: dict[str, QWidget] = {}
        self._components: dict[str, QLabel] = {}
        self._reveals: list[QPushButton] = []
        for (key, title, uses), symbol in zip(PROVIDERS, _SYMBOLS, strict=True):
            if key == "vc_local_api_key":
                title = "Ollama / vLLM"
                uses = "Connect to a running local server."
            card = CatalogRow(symbol=symbol)
            card.set_summary(title, uses, "")
            card.manage.setCheckable(True)
            if key == "vc_local_api_key":
                card.manage.setText("Configure")
            card.manage.clicked.connect(
                lambda checked=False, k=key: self._toggle_editor(k, checked)
            )
            editor = QWidget()
            editor.setObjectName("settingsRow")
            form = SettingsForm(editor)
            component = label("", "settingsHint")
            form.addRow(component)
            self._components[key] = component
            field = QLineEdit(str(settings.get(key, "")))
            field.setEchoMode(QLineEdit.Password)
            field.setPlaceholderText(
                "Optional API key" if key == "vc_local_api_key" else "API key"
            )
            field.setAccessibleName(f"{title} API key")
            field.setAccessibleDescription(uses)
            field.textChanged.connect(lambda _text, k=key: self._update_status(k))
            field_row = QWidget()
            row = QHBoxLayout(field_row)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(field, 1)
            reveal = QPushButton("Show")
            reveal.setCheckable(True)
            reveal.setAutoDefault(False)
            reveal.setAccessibleName(f"Show {title} API key")
            reveal.toggled.connect(partial(self._reveal, field, reveal, title))
            row.addWidget(reveal)
            form.addRow("API key", field_row)
            form.addRow(
                label(
                    "Leave empty to remove this key when you close Settings. "
                    "The connection is not tested here.",
                    "settingsHint",
                )
            )
            components_link = navigation_link("Manage components →")
            components_link.clicked.connect(
                lambda: self.navigate_requested.emit("models:components")
            )
            form.addRow(components_link)
            card.grid.addWidget(editor, 2, 0, 1, 3)
            editor.hide()
            section = self.local if key == "vc_local_api_key" else self.cloud
            section.content.addWidget(card)
            self.fields[key] = field
            self.cards[key] = card
            self.editors[key] = editor
            self._reveals.append(reveal)
        self.llamacpp = CatalogRow(icon="cube")
        self.llamacpp.set_summary(
            "llama.cpp", "Run a GGUF model through RoomKit's managed server.", ""
        )
        self.llamacpp.status.hide()
        self.llamacpp.manage.setText("Models & components →")
        self.llamacpp.manage.setObjectName("settingsLink")
        self.llamacpp.manage.clicked.connect(lambda: self.navigate_requested.emit("models"))
        self.local.content.addWidget(self.llamacpp)
        layout.addWidget(self.cloud)
        self.key_note = label(
            "“Key added” means a value is present. "
            "It does not mean a connection has been verified.",
            "settingsHint",
        )
        layout.addWidget(self.key_note)
        layout.addWidget(self.local)
        self._empty = label("No providers match your search.", "settingsHint")
        layout.addWidget(self._empty)
        layout.addStretch()
        self.search.textChanged.connect(self._filter)
        self.refresh()
        self._filter("")

    def _update_status(self, key: str) -> None:
        missing = [feature for feature in _COMPONENTS[key] if unavailable_reason(feature)]
        has_key = bool(self.fields[key].text().strip())
        text = "Component needed" if missing else "Key added" if has_key else "No key"
        if key == "vc_local_api_key" and not missing and not has_key:
            text = "Key optional"
        self.cards[key].status.set_status(
            text,
            "success"
            if has_key and not missing
            else "neutral"
            if text == "Key optional"
            else "warning",
        )
        self.cards[key].status.setToolTip(
            f"{'Key added' if has_key else 'No key'} · Connection not tested"
        )
        self._components[key].setText(
            "Components needed: " + ", ".join(FEATURES[f].label for f in missing)
            if missing
            else "Required components are installed."
        )

    def refresh(self) -> None:
        for key in self.fields:
            self._update_status(key)

    def _toggle_editor(self, key: str, checked: bool) -> None:
        for candidate, editor in self.editors.items():
            opened = candidate == key and checked
            editor.setVisible(opened)
            self.cards[candidate].manage.setChecked(opened)
            if not opened:
                self._reveals[list(self.fields).index(candidate)].setChecked(False)
        if checked:
            self.fields[key].setFocus()

    def reveal_search_target(self, control: str = "") -> None:
        self.search.clear()
        key = control.removeprefix("fields.")
        if key in self.fields:
            self._toggle_editor(key, True)

    @staticmethod
    def _reveal(field: QLineEdit, button: QPushButton, title: str, checked: bool) -> None:
        field.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        button.setText("Hide" if checked else "Show")
        button.setAccessibleName(f"{'Hide' if checked else 'Show'} {title} API key")

    def _filter(self, query: str) -> None:
        words = query.strip().casefold().split()
        for key, title, uses in PROVIDERS:
            haystack = f"{title} {uses} {self.cards[key].title.text()}".casefold()
            visible = all(word in haystack for word in words)
            self.cards[key].setVisible(visible)
            if not visible:
                self.editors[key].hide()
                self.cards[key].manage.setChecked(False)
                self._reveals[list(self.fields).index(key)].setChecked(False)
        self.llamacpp.setVisible(
            all(word in "llama.cpp local gguf models components" for word in words)
        )
        cloud_rows = [row for key, row in self.cards.items() if key != "vc_local_api_key"]
        local_rows = [self.cards["vc_local_api_key"], self.llamacpp]
        has_cloud = any(not row.isHidden() for row in cloud_rows)
        has_local = any(not row.isHidden() for row in local_rows)
        self.cloud.setVisible(has_cloud)
        self.key_note.setVisible(has_cloud)
        self.local.setVisible(has_local)
        self._empty.setVisible(not (has_cloud or has_local))
        mark_dividers(cloud_rows)
        mark_dividers(local_rows)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        for button in self._reveals:
            button.setChecked(False)
        super().hideEvent(event)

    def get_settings(self) -> dict:
        return {key: field.text().strip() for key, field in self.fields.items()}
