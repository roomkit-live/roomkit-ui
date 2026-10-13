"""Text chat tab: the LLM typed messages run on."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QWidget

from roomkit_ui.widgets.settings.llm_fields import LLMFields

_TEXT_CHAT_HINT = (
    "Typed messages run on this model, with the same instructions, tools and memory "
    "as the voice. Same as Voice Channel takes Think · LLM's model, in Realtime mode "
    "too. A model of its own has the same fields as Think · LLM; its reasoning left "
    "at Model default, it reasons as that model does. Sending images needs a model "
    "that sees them."
)

_TEXT_THINKING_HINT = (
    "Off, a reasoning model (Qwen3, DeepSeek-R1) answers at once. On, it thinks "
    "before each reply, which takes longer."
)


class TextChatSetup(QFrame):
    """The Text chat tab of the Conversation page."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard")
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setContentsMargins(20, 20, 20, 20)
        # The same rows as Think · LLM's and the Agent tab's tasks' model.
        self.llm = LLMFields(
            settings,
            "text",
            parent=self,
            same_label="Same as Voice Channel (Think · LLM)",
            thinking_hints=dict.fromkeys(("local", "llamacpp"), _TEXT_THINKING_HINT),
        )
        self.llm.add_rows(form, "Typed messages run on")
        hint = QLabel(_TEXT_CHAT_HINT)
        hint.setWordWrap(True)
        hint.setObjectName("settingsHint")
        form.addRow("", hint)
        self.llm.update_visibility()

    def get_settings(self) -> dict:
        return self.llm.get_settings()
