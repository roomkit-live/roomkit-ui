"""The spoken language is the user's, set once in General; dictation may set its own."""

import pytest
import shiboken6

from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.stt_sessions import dictation_language
from roomkit_ui.widgets.settings.conversation_page import ConversationPage
from roomkit_ui.widgets.settings.dictation_page import _DictationPage
from roomkit_ui.widgets.settings.general_page import _GeneralPage
from roomkit_ui.widgets.settings.panel import SettingsPanel


@pytest.mark.parametrize(
    ("own", "spoken", "used"),
    [
        ("", "fr", "fr"),  # follows the spoken language
        ("", "", ""),  # which may be detected
        ("de", "fr", "de"),  # its own wins
        ("auto", "fr", ""),  # detected, whatever the spoken language
    ],
)
def test_dictation_follows_the_spoken_language_unless_it_sets_its_own(own, spoken, used):
    assert dictation_language({"dictation_language": own, "stt_language": spoken}) == used


def test_a_saved_spoken_language_keeps_dictation_as_it_was():
    # Before, Dictation's "Spoken language" was stt_language itself.
    assert dictation_language({**_DEFAULTS, "stt_language": "fr"}) == "fr"


def test_general_owns_the_spoken_language(qapp):
    page = _GeneralPage({**_DEFAULTS, "stt_language": "fr"})
    try:
        assert page.spoken_language.currentData() == "fr"
        page.spoken_language.setCurrentIndex(page.spoken_language.findData("es"))
        assert page.get_settings()["stt_language"] == "es"
    finally:
        shiboken6.delete(page)


def test_dictation_saves_only_its_own(qapp):
    page = _DictationPage({**_DEFAULTS, "dictation_language": "auto"})
    try:
        assert page.language.currentData() == "auto"
        out = page.get_settings()
        assert out["dictation_language"] == "auto"
        assert "stt_language" not in out
    finally:
        shiboken6.delete(page)


def test_each_language_has_one_page_owner(qapp):
    panel = SettingsPanel()
    try:
        owners: dict[str, list[str]] = {}
        for key, page in panel._page_widgets.items():
            for name in getattr(page, "get_settings", dict)():
                owners.setdefault(name, []).append(key)
        assert owners["stt_language"] == ["general"]
        assert owners["dictation_language"] == ["dictation"]
    finally:
        shiboken6.delete(panel)


def test_the_stt_and_dictation_pages_lead_to_general(qapp):
    conversation = ConversationPage(dict(_DEFAULTS))
    dictation = _DictationPage(dict(_DEFAULTS))
    try:
        asked: list[str] = []
        conversation.navigate_requested.connect(asked.append)
        dictation.navigate_requested.connect(asked.append)

        conversation.voice.spoken_language_link.click()
        dictation.spoken_language_link.click()

        assert asked == ["general", "general"]
    finally:
        shiboken6.delete(conversation)
        shiboken6.delete(dictation)
