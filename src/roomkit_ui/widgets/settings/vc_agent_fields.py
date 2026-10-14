"""Voice Channel Agent tab: whether the assistant decides when to speak,
thinks while it listens, and works in the background."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.features import SPEAK_POLICY_FEATURES
from roomkit_ui.theme import fixed_font_family
from roomkit_ui.vc_agent import DEFAULT_AGENT_NAME, SPEAK_POLICIES, speak_policy_brief
from roomkit_ui.widgets.settings.controls import label
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo
from roomkit_ui.widgets.settings.llm_fields import LLMFields
from roomkit_ui.widgets.settings.style import settings_stylesheet

_SPEAKING_HINT = (
    "Always answer replies to every turn. Deciding, the assistant stays quiet while "
    "you have not finished, when you put something off or ask for quiet, and only "
    "listens once asked to (“just listen”) until spoken to by its name. Each reply "
    "waits for the decision: about 0.2 s with Jev, up to half a second with OpenAI, "
    "a second or more with the conversation model."
)

_ROLE_HINT = (
    "What the assistant is there for, and for whom, in your words: the deciding model "
    "reads it with every turn, to judge whether a turn is for the assistant."
)

_THINKER_HINT = (
    "On the turns it stays quiet, the conversation model keeps a thought of what "
    "is being said and what the assistant could add; with something worth saying "
    "it may offer it. One more model call per quiet turn. Needs a speaking decision."
)

_BACKGROUND_HINT = (
    "The assistant can hand a long request (a search, a report, several tool calls) "
    "to a task that runs while you keep talking, then tells you the result. The task "
    "has the same tools. On a model of its own it runs beside the conversation model: "
    "a stronger one for the work, or llama.cpp on this computer, with the same fields "
    "as Think · LLM: its reasoning left at Model default, it reasons as that model "
    "does. The session stays open until the task ends."
)

_TASK_THINKING_HINT = (
    "Nobody waits on a task's first word: thinking only makes it take longer. "
    "On llama.cpp, the same GGUF and context as Think · LLM share one server."
)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("settingsHint")
    return label


class VCAgentPage(QFrame):
    """The Agent tab of the Voice Channel section."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard")
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        form.setContentsMargins(20, 20, 20, 20)

        self.speak_policy = QComboBox()
        populate_provider_combo(self.speak_policy, SPEAK_POLICIES, SPEAK_POLICY_FEATURES)
        saved = settings.get("vc_speak_policy", "off")
        for i, (_label, value) in enumerate(SPEAK_POLICIES):
            if value == saved:
                self.speak_policy.setCurrentIndex(i)
                break
        form.addRow("Speaking", self.speak_policy)
        form.addRow("", offer_install(self.speak_policy, SPEAK_POLICIES, SPEAK_POLICY_FEATURES))

        self.agent_name = QLineEdit(settings.get("vc_agent_name", ""))
        self.agent_name.setPlaceholderText(DEFAULT_AGENT_NAME)
        self._agent_name_label = QLabel("Name")
        form.addRow(self._agent_name_label, self.agent_name)

        self.agent_role = QPlainTextEdit(settings.get("vc_agent_role", ""))
        self.agent_role.setPlaceholderText(
            "Sylvain's assistant during his calls and his D&D campaign"
        )
        self.agent_role.setAccessibleName("Role")
        self.agent_role.setTabChangesFocus(True)
        self.agent_role.setFixedHeight(64)
        self._agent_role_label = QLabel("Role")
        form.addRow(self._agent_role_label, self.agent_role)
        self._agent_role_hint = _hint(_ROLE_HINT)
        form.addRow("", self._agent_role_hint)

        self.show_brief = QPushButton("What it is asked…")
        self.show_brief.setAutoDefault(False)
        self.show_brief.setToolTip("What the deciding model reads and answers on each turn")
        self.show_brief.clicked.connect(self._show_brief)
        form.addRow("", self.show_brief)

        form.addRow("", _hint(_SPEAKING_HINT))

        self.thinker = QCheckBox("Think while listening")
        self.thinker.setChecked(bool(settings.get("vc_thinker", False)))
        form.addRow("", self.thinker)
        form.addRow("", _hint(_THINKER_HINT))

        self.background = QCheckBox("Work in the background")
        self.background.setChecked(bool(settings.get("vc_background", False)))
        form.addRow("", self.background)

        # The same rows as Think · LLM's and the Text chat tab's model.
        self.tasks_llm = LLMFields(
            settings,
            "background",
            parent=self,
            same_label="The conversation model",
            thinking=True,
            thinking_hints=dict.fromkeys(("local", "llamacpp"), _TASK_THINKING_HINT),
            tool_use=False,
        )
        self.tasks_llm.add_rows(form, "Tasks run on")
        form.addRow("", _hint(_BACKGROUND_HINT))

        self.speak_policy.currentIndexChanged.connect(self._update_visibility)
        self.background.toggled.connect(self._update_visibility)
        self._update_visibility()

    def current_policy(self) -> str:
        idx: int = self.speak_policy.currentIndex()
        return SPEAK_POLICIES[idx][1]

    def _update_visibility(self) -> None:
        policy = self.current_policy()
        for widget in (
            self._agent_name_label,
            self.agent_name,
            self._agent_role_label,
            self.agent_role,
            self._agent_role_hint,
            self.show_brief,
        ):
            widget.setVisible(policy != "off")
        self.thinker.setEnabled(policy != "off")
        self.tasks_llm.update_visibility(self.background.isChecked())

    def _show_brief(self) -> None:
        """What the deciding model reads and is asked, with the name and role as typed."""
        brief = speak_policy_brief(self.get_settings())
        _BriefDialog(brief, self).exec()

    def get_settings(self) -> dict:
        return {
            "vc_speak_policy": self.current_policy(),
            "vc_agent_name": self.agent_name.text().strip(),
            "vc_agent_role": self.agent_role.toPlainText().strip(),
            "vc_thinker": self.thinker.isChecked(),
            "vc_background": self.background.isChecked(),
            **self.tasks_llm.get_settings(),
        }


class _BriefDialog(QDialog):
    """What the deciding model reads and answers on a turn: roomkit's policy, written out."""

    def __init__(self, brief: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("What it is asked")
        self.setObjectName("settingsPanel")
        self.setStyleSheet(settings_stylesheet(str(QSettings().value("room/theme", "dark"))))
        self.resize(720, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(label("What it is asked", "settingsSectionTitle"))
        layout.addWidget(
            label(
                "On each turn, the deciding model reads the conversation as below and "
                "answers these questions; the answers decide whether the assistant speaks, "
                "offers or stays silent. Written out from roomkit's own policy.",
                "settingsHint",
            )
        )
        self.text = QPlainTextEdit(brief)
        self.text.setReadOnly(True)
        self.text.setAccessibleName("What the deciding model is asked")
        self.text.setStyleSheet(f'font-family: "{fixed_font_family()}"; font-size: 12px;')
        layout.addWidget(self.text, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
