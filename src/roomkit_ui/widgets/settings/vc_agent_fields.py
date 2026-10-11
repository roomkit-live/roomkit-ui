"""Voice Channel Agent tab: whether the assistant decides when to speak,
thinks while it listens, and works in the background."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QFrame, QLabel, QLineEdit, QWidget

from roomkit_ui.features import SPEAK_POLICY_FEATURES
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
    "to a task that runs while you keep talking, then tells you the result. The "
    "task uses the conversation model and the same tools; the session stays open "
    "until it ends."
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

        form.addRow("", _hint(_SPEAKING_HINT))

        self.thinker = QCheckBox("Think while listening")
        self.thinker.setChecked(bool(settings.get("vc_thinker", False)))
        form.addRow("", self.thinker)
        form.addRow("", _hint(_THINKER_HINT))

        self.background = QCheckBox("Work in the background")
        self.background.setChecked(bool(settings.get("vc_background", False)))
        form.addRow("", self.background)
        form.addRow("", _hint(_BACKGROUND_HINT))

        self.speak_policy.currentIndexChanged.connect(self._update_visibility)
        self._update_visibility()

    def current_policy(self) -> str:
        idx: int = self.speak_policy.currentIndex()
        return SPEAK_POLICIES[idx][1]

    def _update_visibility(self) -> None:
        policy = self.current_policy()
        self._agent_name_label.setVisible(policy != "off")
        self.agent_name.setVisible(policy != "off")
        self.thinker.setEnabled(policy != "off")

    def get_settings(self) -> dict:
        return {
            "vc_speak_policy": self.current_policy(),
            "vc_agent_name": self.agent_name.text().strip(),
            "vc_thinker": self.thinker.isChecked(),
            "vc_background": self.background.isChecked(),
        }
