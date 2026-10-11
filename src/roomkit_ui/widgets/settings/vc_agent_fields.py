"""Voice Channel Agent tab: whether the assistant decides when to speak."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QWidget

from roomkit_ui.features import SPEAK_POLICY_FEATURES
from roomkit_ui.theme import colors
from roomkit_ui.vc_agent import DEFAULT_AGENT_NAME, SPEAK_POLICIES
from roomkit_ui.widgets.settings.feature_hints import populate_provider_combo

_SPEAKING_HINT = (
    "Always answer replies to every turn. Deciding, the assistant stays quiet while "
    "you have not finished, when you put something off or ask for quiet, and only "
    "listens once asked to (“just listen”) until spoken to by its name. Each reply "
    "waits for the decision: about 0.2 s with Jev, up to half a second with OpenAI, "
    "a second or more with the conversation model."
)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"font-size: 11px; color: {colors()['TEXT_SECONDARY']};"
        f" font-style: italic; background: transparent;"
    )
    return label


class VCAgentPage(QWidget):
    """The Agent tab of the Voice Channel section."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.speak_policy = QComboBox()
        populate_provider_combo(self.speak_policy, SPEAK_POLICIES, SPEAK_POLICY_FEATURES)
        saved = settings.get("vc_speak_policy", "off")
        for i, (_label, value) in enumerate(SPEAK_POLICIES):
            if value == saved:
                self.speak_policy.setCurrentIndex(i)
                break
        form.addRow("Speaking", self.speak_policy)

        # The OpenAI key is the one every OpenAI field shares (mirrored by the
        # dialog); only TypeSafe's is this tab's own.
        self.openai_api_key = QLineEdit(settings.get("openai_api_key", ""))
        self.openai_api_key.setEchoMode(QLineEdit.Password)
        self.openai_api_key.setPlaceholderText("Enter your OpenAI API key")
        self._openai_key_label = QLabel("API Key")
        form.addRow(self._openai_key_label, self.openai_api_key)

        self.typesafe_api_key = QLineEdit(settings.get("typesafe_api_key", ""))
        self.typesafe_api_key.setEchoMode(QLineEdit.Password)
        self.typesafe_api_key.setPlaceholderText("Enter your TypeSafe API key")
        self._typesafe_key_label = QLabel("API Key")
        form.addRow(self._typesafe_key_label, self.typesafe_api_key)

        self.agent_name = QLineEdit(settings.get("vc_agent_name", ""))
        self.agent_name.setPlaceholderText(DEFAULT_AGENT_NAME)
        self._agent_name_label = QLabel("Name")
        form.addRow(self._agent_name_label, self.agent_name)

        form.addRow("", _hint(_SPEAKING_HINT))

        self.speak_policy.currentIndexChanged.connect(self._update_visibility)
        self._update_visibility()

    def current_policy(self) -> str:
        idx: int = self.speak_policy.currentIndex()
        return SPEAK_POLICIES[idx][1]

    def _update_visibility(self) -> None:
        policy = self.current_policy()
        for label, field, shown in (
            (self._openai_key_label, self.openai_api_key, policy == "openai"),
            (self._typesafe_key_label, self.typesafe_api_key, policy == "jev"),
            (self._agent_name_label, self.agent_name, policy != "off"),
        ):
            label.setVisible(shown)
            field.setVisible(shown)

    def get_settings(self) -> dict:
        return {
            "vc_speak_policy": self.current_policy(),
            "vc_agent_name": self.agent_name.text().strip(),
            "typesafe_api_key": self.typesafe_api_key.text().strip(),
        }
