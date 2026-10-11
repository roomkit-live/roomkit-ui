"""Gemini Live options that depend on the model's generation.

Google changed the Live contract with the 3.8 family: proactive audio is
always on (stating it is refused), affective dialog is gone,
``gemini-3.8-live-extended-thinking`` takes a thinking level, and the family
takes a transcription block for the user's speech.  roomkit's
``live_model_profile`` says what each model accepts; these rows follow it so
a setting never looks active on a model that ignores it.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit, QWidget

THINKING_LEVELS = [
    ("Default (low)", ""),
    ("Low", "LOW"),
    ("Medium", "MEDIUM"),
    ("High", "HIGH"),
]

_PROACTIVE_ALWAYS_ON = "Always on with Gemini 3.8 Live — the API refuses the setting."
_AFFECTIVE_REMOVED = "Removed from the API with Gemini 3.8 Live."


def _live_profile(model: str) -> Any:
    """roomkit's setup profile for *model*, or None if it cannot be read."""
    try:
        from roomkit.providers.gemini.realtime_models import live_model_profile

        return live_model_profile(model)
    except Exception:
        return None


def _is_pre_38(profile: Any) -> bool:
    if profile is None:
        return True
    from roomkit.providers.gemini.realtime_models import PRE_38_PROFILE

    return profile is PRE_38_PROFILE


class GeminiGenerationFields:
    """Rows of the Gemini Advanced form gated on the selected Live model."""

    def __init__(
        self,
        settings: dict,
        form: QFormLayout,
        *,
        proactive: QCheckBox,
        affective: QCheckBox,
    ) -> None:
        self._proactive = proactive
        self._affective = affective
        self._proactive_tip = proactive.toolTip()
        self._affective_tip = affective.toolTip()

        self.thinking_level = QComboBox()
        for label, value in THINKING_LEVELS:
            self.thinking_level.addItem(label, value)
        saved = (settings.get("gemini_thinking_level", "") or "").upper()
        index = self.thinking_level.findData(saved)
        self.thinking_level.setCurrentIndex(max(index, 0))
        self._thinking_label = QLabel("Thinking")
        form.addRow(self._thinking_label, self.thinking_level)

        self.language_auto = QCheckBox("Your language may change mid-conversation")
        self.language_auto.setChecked(bool(settings.get("gemini_language_auto", False)))
        form.addRow("", self.language_auto)

        self.language_hints = QLineEdit(settings.get("gemini_language_hints", "") or "")
        self.language_hints.setPlaceholderText("e.g. fr-FR, en-US")
        self._hints_label = QLabel("You Speak")
        form.addRow(self._hints_label, self.language_hints)

        self.custom_vocabulary = QLineEdit(settings.get("gemini_custom_vocabulary", "") or "")
        self.custom_vocabulary.setPlaceholderText("Names and terms, comma-separated")
        self._vocabulary_label = QLabel("Vocabulary")
        form.addRow(self._vocabulary_label, self.custom_vocabulary)

    def update_for_model(self, model: str) -> None:
        """Show, enable or explain each row for what *model* accepts."""
        profile = _live_profile(model)
        pre_38 = _is_pre_38(profile)
        self._proactive.setEnabled(pre_38)
        self._proactive.setToolTip(self._proactive_tip if pre_38 else _PROACTIVE_ALWAYS_ON)
        self._affective.setEnabled(pre_38)
        self._affective.setToolTip(self._affective_tip if pre_38 else _AFFECTIVE_REMOVED)

        thinking = bool(profile is not None and profile.thinking_level)
        self._set_rows_visible(thinking, self._thinking_label, self.thinking_level)
        self._set_rows_visible(
            not pre_38,
            self.language_auto,
            self._hints_label,
            self.language_hints,
            self._vocabulary_label,
            self.custom_vocabulary,
        )

    @staticmethod
    def _set_rows_visible(visible: bool, *widgets: QWidget) -> None:
        for widget in widgets:
            widget.setVisible(visible)

    def get_settings(self) -> dict:
        return {
            "gemini_thinking_level": self.thinking_level.currentData() or "",
            "gemini_language_auto": self.language_auto.isChecked(),
            "gemini_language_hints": self.language_hints.text().strip(),
            "gemini_custom_vocabulary": self.custom_vocabulary.text().strip(),
        }
