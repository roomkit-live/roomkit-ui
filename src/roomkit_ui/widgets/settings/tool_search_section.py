"""Tool Search: when the assistant looks its tools up instead of seeing them all."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QSpinBox

from roomkit_ui.toolset import tool_search_options
from roomkit_ui.widgets.settings.controls import SettingsSection

TOOL_SEARCH_CHOICES = [
    ("Automatic", "auto"),
    ("Always search", "on"),
    ("Never: every tool in the prompt", "off"),
]


def _spin(minimum: int, maximum: int, value: int, suffix: str, step: int = 1) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setSuffix(suffix)
    spin.setValue(min(max(value, minimum), maximum))
    return spin


class ToolSearchSection(SettingsSection):
    """The Tool Search mode and the thresholds its automatic mode decides on.

    roomkit hides a large catalogue behind ``find_tools``: the model sees a
    few tools and searches for the rest.  A realtime channel counts tools; the
    Voice Channel's model weighs their schemas against a token budget and its
    context window.  The thresholds apply in Automatic only, except the tool
    count, which also caps how many tools a realtime model sees at once.
    """

    def __init__(self, settings: dict) -> None:
        super().__init__(
            "Tool search",
            "With many tools, the assistant sees a few and finds the others with "
            "find_tools. Fewer tools in the prompt keep a model's choice reliable and "
            "its turns cheaper; a search costs a step before the call.",
        )
        options = tool_search_options(settings, realtime=False)

        self.mode = QComboBox()
        for title, value in TOOL_SEARCH_CHOICES:
            self.mode.addItem(title, value)
        # An unknown saved mode reads as Automatic, as toolset reads it.
        self.mode.setCurrentIndex(max(self.mode.findData(settings.get("tool_search_mode")), 0))
        self.add_row(
            "Search for tools",
            "Automatic searches once the tools pass the thresholds below, never with a "
            "local model (Ollama, vLLM, llama.cpp): a small model may not look its tools up.",
            self.mode,
        )

        self.threshold = _spin(1, 200, options["tool_search_threshold"], " tools")
        self.add_row(
            "Realtime threshold",
            "A realtime model searches above this many tools and sees at most this many "
            "at once. Google recommends 10 to 20 for Gemini Live. A Voice Channel model "
            "whose context window is unknown uses it too.",
            self.threshold,
        )
        self.tokens = _spin(500, 200_000, options["tool_search_threshold_tokens"], " tokens", 500)
        self.add_row(
            "Voice Channel budget",
            "The Voice Channel's model searches once the tools' descriptions would take "
            "more than this. Past about 8000, searching costs less than sending them all.",
            self.tokens,
        )
        self.window_pct = _spin(1, 100, int(options["tool_search_threshold_pct"]), " %")
        self.add_row(
            "Share of the context window",
            "It also searches once they would fill more than this share of the model's "
            "context window, which matters for a model with a small one.",
            self.window_pct,
        )

        self.mode.currentIndexChanged.connect(self._update_enabled)
        self._update_enabled()

    def _update_enabled(self) -> None:
        mode = self.mode.currentData()
        # Disabled, each keeps its value for when Automatic comes back.
        self.threshold.setEnabled(mode != "off")
        self.tokens.setEnabled(mode == "auto")
        self.window_pct.setEnabled(mode == "auto")

    def get_settings(self) -> dict:
        return {
            "tool_search_mode": self.mode.currentData() or "auto",
            "tool_search_threshold": self.threshold.value(),
            "tool_search_threshold_tokens": self.tokens.value(),
            "tool_search_window_pct": self.window_pct.value(),
        }
