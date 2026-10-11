"""Speakers tab, Meta Muse part: who the user is among the voices Muse tells apart."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from roomkit_ui.theme import colors

_HINT = (
    "With Meta Muse as the Voice Channel STT, the voices show as Speaker A, B… in "
    "the chat: click one to say who it is, and the assistant names those who "
    "introduce themselves. Muse knows nobody from one session to the next. The "
    "voice carrying your name is yours, which is what “Listen only to primary "
    "speaker” lets through."
)

_FIRST_VOICE_HINT = (
    "You open the session, so the first voice is usually yours. Whoever speaks "
    "first is taken as you, though: with someone else talking first, click the "
    "names to put it right."
)


class MuseSpeakersSection(QWidget):
    """Your name, and whether the first voice of a session is taken as yours."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        c = colors()
        secondary = f"color: {c['TEXT_SECONDARY']}; background: transparent;"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("With Meta Muse")
        title.setStyleSheet(
            f"font-size: 12px; font-weight: 600; {secondary}"
            " text-transform: uppercase; letter-spacing: 1px;"
        )
        layout.addWidget(title)
        layout.addWidget(_wrapped(_HINT, f"font-size: 12px; {secondary}"))

        row = QHBoxLayout()
        label = QLabel("Your name:")
        label.setStyleSheet(f"font-size: 13px; {secondary}")
        row.addWidget(label)
        self.user_name = QLineEdit(settings.get("user_name", ""))
        self.user_name.setPlaceholderText(_placeholder())
        self.user_name.setMaxLength(40)
        row.addWidget(self.user_name, 1)
        layout.addLayout(row)

        self.first_voice = QCheckBox("The first voice is me")
        self.first_voice.setChecked(bool(settings.get("speaker_first_voice_is_user", True)))
        layout.addWidget(self.first_voice)
        layout.addWidget(_wrapped(_FIRST_VOICE_HINT, f"font-size: 12px; {secondary}"))

    def get_settings(self) -> dict:
        return {
            "user_name": " ".join(self.user_name.text().split()),
            "speaker_first_voice_is_user": self.first_voice.isChecked(),
        }


def _placeholder() -> str:
    """The name used when the field is empty: the primary speaker's, else "User"."""
    from roomkit_ui.speaker_manager import get_primary_speaker

    primary = get_primary_speaker()
    return primary.name if primary is not None else "User"


def _wrapped(text: str, style: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(style)
    return label
