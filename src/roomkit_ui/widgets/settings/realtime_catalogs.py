"""What the realtime settings offer: providers, models, voices, languages.

Model and voice lists come from roomkit's offline catalogs (pure-data
modules, no vendor SDK); the hardcoded lineups below are the fallbacks used
when a catalog cannot be imported.  The combo helpers keep a saved id that
is not in the lineup, rather than silently replacing it.
"""

from __future__ import annotations

import importlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox

PROVIDERS = [
    ("Google Gemini", "gemini"),
    ("OpenAI", "openai"),
    ("Deepgram Voice Agent", "deepgram"),
    ("ElevenLabs (Conversational AI)", "elevenlabs"),
    ("xAI Grok", "xai"),
    ("OpenAI GPT-Live (full-duplex)", "openai_live"),
]

# Fallback STS model ids, used until the installed roomkit ships the
# realtime_models catalogs (added upstream for 0.44; 0.43 has none — the chat
# catalogs exclude realtime ids on purpose).  The STS model combos are fixed
# dropdowns: a saved id outside the lineup is inserted, not silently replaced.
GEMINI_MODELS = [
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-3.1-flash-live-preview",
    "gemini-2.0-flash-live-001",
]
# Fallback ids, used only when roomkit's offline voice catalog fails to import.
GEMINI_VOICES = ["Aoede", "Charon", "Fenrir", "Kore", "Puck"]

GEMINI_LANGUAGES = [
    ("Auto-detect", ""),
    ("English (US)", "en-US"),
    ("English (UK)", "en-GB"),
    ("French", "fr-FR"),
    ("Spanish", "es-ES"),
    ("German", "de-DE"),
    ("Italian", "it-IT"),
    ("Portuguese (BR)", "pt-BR"),
    ("Dutch", "nl-NL"),
    ("Japanese", "ja-JP"),
    ("Chinese", "zh-CN"),
    ("Korean", "ko-KR"),
    ("Russian", "ru-RU"),
    ("Arabic", "ar-XA"),
    ("Hindi", "hi-IN"),
]

OPENAI_MODELS = [
    "gpt-realtime-2.1",
    "gpt-realtime-2.1-mini",
    "gpt-realtime-1.5",
    "gpt-4o-realtime-preview",
]
OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

# Fallback Aura-2 ids (the catalog has ~90 live voices; the combo stays
# editable so any "aura-2-{name}-{lang}" id can be typed either way).
DEEPGRAM_VOICES = [
    "aura-2-thalia-en",
    "aura-2-andromeda-en",
    "aura-2-apollo-en",
    "aura-2-asteria-en",
    "aura-2-athena-en",
    "aura-2-atlas-en",
    "aura-2-helena-en",
    "aura-2-hermes-en",
    "aura-2-orion-en",
    "aura-2-agathe-fr",
    "aura-2-hector-fr",
]
DEEPGRAM_THINK_PROVIDERS = [
    ("OpenAI", "open_ai"),
    ("Anthropic", "anthropic"),
    ("Google", "google"),
]

# Listen (STT) languages.  nova-3 monolingual is English-only: picking a
# specific language with the model on Auto makes the engine select nova-2;
# "Multilingual" rides nova-3's code-switching mode.
DEEPGRAM_LANGUAGES = [
    ("English (default)", ""),
    ("Multilingual (nova-3)", "multi"),
    ("French", "fr"),
    ("Spanish", "es"),
    ("German", "de"),
    ("Portuguese", "pt"),
    ("Italian", "it"),
    ("Dutch", "nl"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("Russian", "ru"),
    ("Hindi", "hi"),
]

DEEPGRAM_LISTEN_MODELS = ["nova-3", "nova-2", "flux-general-en"]

# Deepgram's think stage speaks each vendor's chat API, so roomkit's chat
# model catalogs (pure-data modules) are the right suggestion source.
DEEPGRAM_THINK_CATALOGS = {
    "open_ai": "roomkit.providers.openai.models",
    "anthropic": "roomkit.providers.anthropic.models",
    "google": "roomkit.providers.gemini.models",
}

XAI_MODELS = ["grok-2-audio"]
XAI_VOICES = ["eve", "ara", "rex", "sal", "leo"]


def chat_model_options(module_name: str) -> list[str]:
    """Model ids from a roomkit chat catalog (``MODELS: list[ModelInfo]``).

    Same import economics as the voice catalogs: pure data, no vendor SDK.
    An unknown module or a shape change yields an empty list — the combo is
    editable, so suggestions are decoration, never a gate.
    """
    try:
        models = importlib.import_module(module_name).MODELS
        return [m.id for m in models]
    except Exception:
        return []


def sts_model_options(module_name: str, fallback: list[str]) -> list[str]:
    """STS model ids from a roomkit ``realtime_models`` catalog, or *fallback*.

    The catalogs land in roomkit 0.44 (``providers/*/realtime_models.py``);
    on 0.43 the import fails and the hardcoded lineup answers instead.
    Deprecated ids (the retired gpt-4o previews) are dropped — anyone still
    pinning one can type it, the combos being editable.
    """
    try:
        models = importlib.import_module(module_name).MODELS
        ids = [m.id for m in models if not m.deprecated]
        return ids or fallback
    except Exception:
        return fallback


def voice_options(module_name: str, fallback: list[str]) -> list[tuple[str, str]]:
    """``(voice_id, traits)`` pairs from a roomkit offline voice catalog.

    The catalogs are pure-data modules (no vendor SDK import), but the first
    one still pays roomkit's package import (~0.5 s cold) — acceptable once
    per process, at dialog-open time.  Deprecated voices (e.g. Deepgram's
    Aura-1 line) are dropped.  Falls back to the bare id list on any import
    problem so the dialog never breaks with the catalog.
    """
    try:
        voices = importlib.import_module(module_name).VOICES
    except Exception:
        return [(vid, "") for vid in fallback]
    options = [
        (v.id, ", ".join(t for t in (v.gender, v.description) if t))
        for v in voices
        if not v.deprecated
    ]
    return options or [(vid, "") for vid in fallback]


def populate_model_combo(combo: QComboBox, options: list[str], current: str) -> None:
    """Fill a fixed model dropdown and restore the selection.

    A saved id the lineup does not carry (legacy default, hand-pinned model)
    is inserted at the top and stays selectable — replacing it silently would
    change what the next session runs.
    """
    combo.addItems(options)
    if current:
        idx = combo.findText(current)
        if idx < 0:
            combo.insertItem(0, current)
            idx = 0
        combo.setCurrentIndex(idx)


def populate_voice_combo(combo: QComboBox, options: list[tuple[str, str]], current: str) -> None:
    """Fill a voice combo with catalog entries and restore the selection.

    Item data always carries the bare voice id.  Editable combos show the id
    itself (the text doubles as free input); fixed combos show ``id — traits``.
    """
    editable = combo.isEditable()
    for vid, traits in options:
        label = vid if editable or not traits else f"{vid} — {traits[:48]}"
        combo.addItem(label, vid)
        if traits:
            combo.setItemData(combo.count() - 1, traits, Qt.ToolTipRole)
    idx = combo.findData(current)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    elif editable:
        combo.setCurrentText(current)
