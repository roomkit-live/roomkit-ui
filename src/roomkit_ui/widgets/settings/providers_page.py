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
        "Realtime, GPT-Live, conversation, dictation, speaking decisions and images",
    ),
    (
        "api_key",
        "Google Gemini",
        "Gemini Live, conversation, transcription, speech synthesis and images",
    ),
    ("anthropic_api_key", "Anthropic", "Conversation and Deepgram agent reasoning"),
    ("deepgram_api_key", "Deepgram", "Voice Agent, transcription and dictation"),
    ("elevenlabs_api_key", "ElevenLabs", "Conversational AI and speech synthesis"),
    ("gradium_api_key", "Gradium", "Transcription and speech synthesis"),
    ("xai_api_key", "xAI", "Grok realtime conversations and images"),
    ("azure_speech_api_key", "Microsoft Azure", "MAI transcription and speech synthesis"),
    ("meta_api_key", "Meta", "Muse Voice transcription, speaker identification and images"),
    ("typesafe_api_key", "TypeSafe", "Jev speaking decisions"),
    (
        "huggingface_token",
        "Hugging Face",
        "Downloads of llama.cpp models, gated ones included",
    ),
    (
        "vc_local_api_key",
        "Local server",
        "Optional authentication for an OpenAI-compatible server",
    ),
)


_SYMBOLS = ("◎", "✦", "A", "D", "Ⅱ", "G", "x", "Az", "M", "T", "HF", ">_")
# Rows of the "Local providers" section; the others are cloud providers.
_LOCAL = ("huggingface_token", "vc_local_api_key")
# A key some rows may go without, and what to call it.
_OPTIONAL = {
    "vc_local_api_key": "Key optional",
    "huggingface_token": "Token optional",  # nosec B105 — a status label
}


def credential_name(key: str) -> str:
    """What the provider calls the credential: an access token, or an API key."""
    return "access token" if key == "huggingface_token" else "API key"


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
    "huggingface_token": ("llamacpp",),
    "vc_local_api_key": ("openai",),
}


_HF_HINT = (
    "Optional: models anyone may download need no token. A gated model (Llama, "
    "Gemma) needs one, from an account that accepted its terms; a token also raises "
    "Hugging Face's request limits. Only downloads use it. Leave empty to remove it "
    "when you close Settings."
)


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
            credential = credential_name(key)
            field = QLineEdit(str(settings.get(key, "")))
            field.setEchoMode(QLineEdit.Password)
            field.setPlaceholderText(
                f"Optional {credential}" if key in _OPTIONAL else credential.capitalize()
            )
            field.setAccessibleName(f"{title} {credential}")
            field.setAccessibleDescription(uses)
            field.textChanged.connect(lambda _text, k=key: self._update_status(k))
            field_row = QWidget()
            row = QHBoxLayout(field_row)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(field, 1)
            reveal = QPushButton("Show")
            reveal.setCheckable(True)
            reveal.setAutoDefault(False)
            reveal.setAccessibleName(f"Show {title} {credential}")
            reveal.toggled.connect(partial(self._reveal, field, reveal, f"{title} {credential}"))
            row.addWidget(reveal)
            form.addRow(credential.capitalize(), field_row)
            form.addRow(
                label(
                    _HF_HINT
                    if key == "huggingface_token"
                    else "Leave empty to remove this key when you close Settings. "
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
            section = self.local if key in _LOCAL else self.cloud
            section.content.addWidget(card)
            self.fields[key] = field
            self.cards[key] = card
            self.editors[key] = editor
            self._reveals.append(reveal)
        self.llamacpp = CatalogRow(icon="cube")
        self.llamacpp.set_summary(
            "llama.cpp",
            "Run a GGUF model through RoomKit's managed server. Download one in "
            "Models & components → LLMs.",
            "",
        )
        self.llamacpp.status.hide()
        self.llamacpp.manage.setText("Local LLMs →")
        self.llamacpp.manage.setObjectName("settingsLink")
        self.llamacpp.manage.clicked.connect(lambda: self.navigate_requested.emit("models:llms"))
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
        noun = "Token" if key == "huggingface_token" else "Key"
        stored = f"{noun} added" if has_key else f"No {noun.lower()}"
        text = "Component needed" if missing else stored
        if key in _OPTIONAL and not missing and not has_key:
            text = _OPTIONAL[key]
        self.cards[key].status.set_status(
            text,
            "success"
            if has_key and not missing
            else "neutral"
            if text in _OPTIONAL.values()
            else "warning",
        )
        self.cards[key].status.setToolTip(f"{stored} · Connection not tested")
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
    def _reveal(field: QLineEdit, button: QPushButton, name: str, checked: bool) -> None:
        field.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        button.setText("Hide" if checked else "Show")
        button.setAccessibleName(f"{'Hide' if checked else 'Show'} {name}")

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
        cloud_rows = [row for key, row in self.cards.items() if key not in _LOCAL]
        local_rows = [*(self.cards[key] for key in _LOCAL), self.llamacpp]
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
