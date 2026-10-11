"""OpenAI GPT-Live settings: the full-duplex live model and its hosted backend.

GPT-Live listens while it speaks and hands reasoning and tool use to a
backend model OpenAI hosts.  Models, voices and backend models come from
roomkit's offline catalogs, like the other realtime providers' combos.
"""

from __future__ import annotations

import importlib

from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QWidget

LIVE_MODELS = ["gpt-live-1"]  # used only if roomkit's catalog cannot be read
LIVE_VOICES = ["marin"]
BACKEND_EFFORTS = [("Low (fastest)", "low"), ("Medium", "medium"), ("High", "high")]


def _live_models() -> list[str]:
    try:
        models = importlib.import_module("roomkit.providers.openai.live_models").MODELS
        return [m.id for m in models if not m.deprecated] or LIVE_MODELS
    except Exception:
        return LIVE_MODELS


def _live_voices() -> list[tuple[str, str]]:
    """``(voice_id, traits)`` from GPT-Live's own catalog (its voices are not Realtime's)."""
    try:
        live = importlib.import_module("roomkit.providers.openai.live")
        voices = live.OpenAILiveProvider.available_voices()
    except Exception:
        return [(vid, "") for vid in LIVE_VOICES]
    return [
        (v.id, ", ".join(t for t in (v.language, v.gender, v.description) if t)) for v in voices
    ]


def _backend_models() -> list[str]:
    """Current OpenAI models: the backend is a Responses model, any of them."""
    try:
        models = importlib.import_module("roomkit.providers.openai.models").MODELS
        return [m.id for m in models if not m.deprecated]
    except Exception:
        return []


class GPTLiveFields:
    """GPT-Live rows of the realtime form; ``widgets`` lists what to show for it."""

    def __init__(self, settings: dict, form: QFormLayout) -> None:
        self.model = QComboBox()
        self.model.addItems(_live_models())
        _select_text(self.model, settings.get("openai_live_model", "") or "gpt-live-1")

        self.voice = QComboBox()
        for vid, traits in _live_voices():
            self.voice.addItem(f"{vid} — {traits[:48]}" if traits else vid, vid)
        index = self.voice.findData(settings.get("openai_live_voice", "") or "marin")
        self.voice.setCurrentIndex(max(index, 0))

        self.backend_model = QComboBox()
        self.backend_model.setEditable(True)
        self.backend_model.addItems(_backend_models())
        self.backend_model.setCurrentText(
            settings.get("openai_live_backend_model", "") or "gpt-5.6-terra"
        )
        self.backend_model.setToolTip(
            "The model OpenAI runs when GPT-Live delegates: it reasons and calls the tools."
        )

        self.backend_effort = QComboBox()
        for label, value in BACKEND_EFFORTS:
            self.backend_effort.addItem(label, value)
        index = self.backend_effort.findData(settings.get("openai_live_backend_effort", "low"))
        self.backend_effort.setCurrentIndex(max(index, 0))

        self.note = QLabel(
            "Full-duplex: it keeps listening while it speaks, so talk over it at will. "
            "Keep echo cancellation on (or wear headphones) so it does not hear itself."
        )
        self.note.setWordWrap(True)
        self.note.setObjectName("settingsHint")
        self.widgets: list[QWidget] = [self.note]
        for label_text, field in (
            ("Model", self.model),
            ("Voice", self.voice),
            ("Tools Model", self.backend_model),
            ("Tools Effort", self.backend_effort),
        ):
            row_label = QLabel(label_text)
            form.addRow(row_label, field)
            self.widgets += [row_label, field]
        form.addRow("", self.note)

    def get_settings(self) -> dict:
        return {
            "openai_live_model": self.model.currentText().strip(),
            "openai_live_voice": self.voice.currentData() or "",
            "openai_live_backend_model": self.backend_model.currentText().strip(),
            "openai_live_backend_effort": self.backend_effort.currentData() or "low",
        }


def _select_text(combo: QComboBox, current: str) -> None:
    """Select *current*; a saved id the lineup lacks is inserted, not replaced."""
    index = combo.findText(current)
    if index < 0:
        combo.insertItem(0, current)
        index = 0
    combo.setCurrentIndex(index)
