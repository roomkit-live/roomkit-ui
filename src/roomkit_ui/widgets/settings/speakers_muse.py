"""Speakers tab, Meta Muse part: who the user is among the voices Muse tells apart."""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QWidget

from roomkit_ui.widgets.settings.controls import SettingsForm, SettingsSection, SettingsToggle

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


class MuseSpeakersSection(SettingsSection):
    """Your name, and whether the first voice of a session is taken as yours."""

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__("With Meta Muse", _HINT)
        if parent is not None:
            self.setParent(parent)
        form = SettingsForm()
        form.setContentsMargins(20, 18, 20, 18)
        self.user_name = QLineEdit(settings.get("user_name", ""))
        self.user_name.setPlaceholderText(_placeholder())
        self.user_name.setMaxLength(40)
        form.addRow("Your name", self.user_name)
        self.content.addLayout(form)
        self.first_voice = SettingsToggle(
            "The first voice is me", bool(settings.get("speaker_first_voice_is_user", True))
        )
        self.add_row("The first voice is me", _FIRST_VOICE_HINT, self.first_voice)

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
