"""The chat names the voices the STT tells apart: relabel, and a plain click to rename."""

import shiboken6

from roomkit_ui.widgets.chat_view import ChatView


def _speakers(chat: ChatView) -> list[str]:
    return [b._speaker_label.text() for b in chat._bubbles() if b._speaker_label is not None]


def test_a_named_voice_relabels_its_turns_past_and_to_come(qapp):
    chat = ChatView()
    try:
        chat.name_voice("Speaker A", "Speaker A")
        chat.name_voice("Speaker B", "Speaker B")
        chat.add_transcription("salut", "user", True, "Speaker A")
        chat.add_transcription("bonjour", "user", True, "Speaker B")

        chat.name_voice("Speaker B", "Julie")
        chat.add_transcription("ça va ?", "user", True, "Speaker B")

        assert _speakers(chat) == ["Speaker A", "Julie", "Julie"]
        assert chat.given_names() == ["Julie"]
        assert chat.voice_name("Speaker B") == "Julie"
    finally:
        shiboken6.delete(chat)


def test_a_click_on_a_voice_asks_to_name_it(qapp):
    chat = ChatView()
    clicked: list[str] = []
    chat.speaker_clicked.connect(clicked.append)
    try:
        chat.name_voice("Speaker B", "Julie")
        chat.add_transcription("bonjour", "user", True, "Speaker B")
        (bubble,) = chat._bubbles()

        bubble._speaker_label.clicked.emit()

        assert clicked == ["Speaker B"]
        assert bubble._speaker_label._clickable
    finally:
        shiboken6.delete(chat)


def test_an_enrolled_speaker_or_an_unattributed_turn_is_not_clickable(qapp):
    chat = ChatView()
    try:
        chat.add_transcription("hello", "user", True, "Alice")  # local identification
        chat.add_transcription("hm", "user", True, "Unknown speaker")

        assert [b._speaker_label._clickable for b in chat._bubbles()] == [False, False]
        assert _speakers(chat) == ["Alice", "Unknown speaker"]
    finally:
        shiboken6.delete(chat)


def test_a_new_session_forgets_the_voices(qapp):
    chat = ChatView()
    try:
        chat.name_voice("Speaker A", "Sylvain")
        chat.clear()
        chat.add_transcription("hello", "user", True, "Speaker A")

        assert _speakers(chat) == ["Speaker A"]
        assert chat.given_names() == []
    finally:
        shiboken6.delete(chat)


def _answer(text: str | None):
    """Answer the next dialog: type *text* and accept, or dismiss it on None."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QInputDialog

    def act():
        dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QInputDialog))
        if text is None:
            dialog.reject()
        else:
            dialog.setTextValue(text)
            dialog.accept()

    QTimer.singleShot(0, act)


def test_the_dialog_returns_the_name_given_and_none_when_dismissed(qapp):
    from roomkit_ui.widgets.voice_name_dialog import ask_voice_name

    _answer("  Julie   Martin ")
    assert ask_voice_name(None, "Speaker B", "Speaker B", ["Sylvain"]) == "Julie Martin"
    _answer("")
    assert ask_voice_name(None, "Speaker B", "Julie", ["Sylvain"]) == ""
    _answer(None)
    assert ask_voice_name(None, "Speaker B", "Julie", []) is None
