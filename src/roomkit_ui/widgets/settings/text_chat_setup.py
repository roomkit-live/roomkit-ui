"""Text chat tab: the LLM typed messages run on."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QWidget

from roomkit_ui.widgets.settings.llm_role_fields import RoleLLMFields

_TEXT_CHAT_HINT = (
    "Typed messages run on this model, with the same instructions, tools and memory "
    "as the voice. Same as Voice Channel takes Think · LLM's model, in Realtime mode "
    "too. A cloud model of its own reasons as it does by default. Sending images "
    "needs a model that sees them."
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
        self.llm = RoleLLMFields(
            settings,
            "text",
            same_label="Same as Voice Channel (Think · LLM)",
            thinking=False,
            thinking_hint=_TEXT_THINKING_HINT,
            tool_use=True,
            parent=self,
        )
        self.llm.add_rows(form, "Typed messages run on")
        hint = QLabel(_TEXT_CHAT_HINT)
        hint.setWordWrap(True)
        hint.setObjectName("settingsHint")
        form.addRow("", hint)
        self.llm.update_visibility()

    def get_settings(self) -> dict:
        return self.llm.get_settings()
