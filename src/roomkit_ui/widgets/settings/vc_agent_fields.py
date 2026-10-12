"""Voice Channel Agent tab: whether the assistant decides when to speak,
thinks while it listens, and works in the background."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from roomkit_ui.features import AI_PROVIDER_FEATURES, SPEAK_POLICY_FEATURES
from roomkit_ui.vc_agent import DEFAULT_AGENT_NAME, SPEAK_POLICIES
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo

_SPEAKING_HINT = (
    "Always answer replies to every turn. Deciding, the assistant stays quiet while "
    "you have not finished, when you put something off or ask for quiet, and only "
    "listens once asked to (“just listen”) until spoken to by its name. Each reply "
    "waits for the decision: about 0.2 s with Jev, up to half a second with OpenAI, "
    "a second or more with the conversation model."
)

_THINKER_HINT = (
    "On the turns it stays quiet, the conversation model keeps a thought of what "
    "is being said and what the assistant could add; with something worth saying "
    "it may offer it. One more model call per quiet turn. Needs a speaking decision."
)

_BACKGROUND_HINT = (
    "The assistant can hand a long request (a search, a report, several tool calls) "
    "to a task that runs while you keep talking, then tells you the result. The task "
    "has the same tools. On llama.cpp it runs on this computer, while the conversation "
    "model talks. The session stays open until the task ends."
)

_TASK_THINKING_HINT = (
    "Nobody waits on a task's first word: thinking only makes it take longer. Its "
    "server starts at the first task; the same GGUF and context as Think · LLM share "
    "one server."
)

# (label, vc_background_model)
BACKGROUND_MODELS: list[tuple[str, str]] = [
    ("The conversation model", ""),
    ("llama.cpp (local GGUF)", "llamacpp"),
]


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

        form.addRow("", _hint(_SPEAKING_HINT))

        self.thinker = QCheckBox("Think while listening")
        self.thinker.setChecked(bool(settings.get("vc_thinker", False)))
        form.addRow("", self.thinker)
        form.addRow("", _hint(_THINKER_HINT))

        self.background = QCheckBox("Work in the background")
        self.background.setChecked(bool(settings.get("vc_background", False)))
        form.addRow("", self.background)

        self.background_model = QComboBox()
        populate_provider_combo(self.background_model, BACKGROUND_MODELS, AI_PROVIDER_FEATURES)
        saved_model = settings.get("vc_background_model", "")
        for i, (_label, value) in enumerate(BACKGROUND_MODELS):
            if value == saved_model:
                self.background_model.setCurrentIndex(i)
                break
        form.addRow("Tasks run on", self.background_model)
        form.addRow(
            "", offer_install(self.background_model, BACKGROUND_MODELS, AI_PROVIDER_FEATURES)
        )
        self._add_task_llamacpp_fields(form, settings)
        form.addRow("", _hint(_BACKGROUND_HINT))

        self.speak_policy.currentIndexChanged.connect(self._update_visibility)
        self.background.toggled.connect(self._update_visibility)
        self.background_model.currentIndexChanged.connect(self._update_visibility)
        self._update_visibility()

    def _add_task_llamacpp_fields(self, form: QFormLayout, settings: dict) -> None:
        """The tasks' llama.cpp model: its GGUF and context, empty taking
        Think · LLM's, and whether it thinks."""
        from roomkit_ui.providers.llamacpp import DEFAULT_MODEL

        conversation_model = settings.get("vc_llamacpp_model") or DEFAULT_MODEL
        self.task_gguf = QLineEdit(settings.get("vc_background_llamacpp_model", ""))
        self.task_gguf.setPlaceholderText(f"As in Think · LLM: {_short_model(conversation_model)}")
        self.task_gguf.setToolTip(
            "A Hugging Face GGUF as repo:quant, or the path of a local .gguf file."
        )
        browse = QPushButton("Browse…")
        browse.setCursor(Qt.PointingHandCursor)
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse_gguf)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.task_gguf, 1)
        row.addWidget(browse)
        self._task_gguf_label = QLabel("GGUF Model")
        form.addRow(self._task_gguf_label, row)
        self._task_browse = browse

        conversation_context = settings.get("vc_llamacpp_context") or "8192"
        self.task_context = QLineEdit(str(settings.get("vc_background_llamacpp_context") or ""))
        self.task_context.setPlaceholderText(
            f"As in Think · LLM: {conversation_context} (tokens; tools count against it)"
        )
        self._task_context_label = QLabel("Context")
        form.addRow(self._task_context_label, self.task_context)

        self.task_thinking = QCheckBox("Model thinking")
        self.task_thinking.setChecked(bool(settings.get("vc_background_llamacpp_thinking", True)))
        self._task_thinking_label = QLabel("")
        form.addRow(self._task_thinking_label, self.task_thinking)
        self._task_thinking_hint = _hint(_TASK_THINKING_HINT)
        form.addRow("", self._task_thinking_hint)

    def _task_llamacpp_widgets(self) -> tuple[QWidget, ...]:
        return (
            self._task_gguf_label,
            self.task_gguf,
            self._task_browse,
            self._task_context_label,
            self.task_context,
            self._task_thinking_label,
            self.task_thinking,
            self._task_thinking_hint,
        )

    def _browse_gguf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a GGUF Model", "", "GGUF models (*.gguf)"
        )
        if path:
            self.task_gguf.setText(path)

    def current_policy(self) -> str:
        idx: int = self.speak_policy.currentIndex()
        return SPEAK_POLICIES[idx][1]

    def _update_visibility(self) -> None:
        policy = self.current_policy()
        self._agent_name_label.setVisible(policy != "off")
        self.agent_name.setVisible(policy != "off")
        self.thinker.setEnabled(policy != "off")
        background = self.background.isChecked()
        self.background_model.setEnabled(background)
        on_llamacpp = self._background_model() == "llamacpp"
        for widget in self._task_llamacpp_widgets():
            widget.setVisible(on_llamacpp)
            widget.setEnabled(background)

    def _background_model(self) -> str:
        return BACKGROUND_MODELS[self.background_model.currentIndex()][1]

    def get_settings(self) -> dict:
        return {
            "vc_speak_policy": self.current_policy(),
            "vc_agent_name": self.agent_name.text().strip(),
            "vc_thinker": self.thinker.isChecked(),
            "vc_background": self.background.isChecked(),
            "vc_background_model": self._background_model(),
            "vc_background_llamacpp_model": self.task_gguf.text().strip(),
            "vc_background_llamacpp_context": self.task_context.text().strip(),
            "vc_background_llamacpp_thinking": self.task_thinking.isChecked(),
        }


def _short_model(model: str) -> str:
    """A GGUF path by its file name; a repo:quant as it is."""
    return Path(model).name if model.endswith(".gguf") else model
