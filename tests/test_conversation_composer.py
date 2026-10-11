"""The mobile-sized home only opens Live; future text input cannot send."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from roomkit_ui.engine_state import EngineState
from roomkit_ui.theme_live import apply_theme
from roomkit_ui.widgets.conversation_composer import ConversationComposer


def test_text_is_unavailable_but_live_works_from_the_keyboard(qtbot):
    composer = ConversationComposer()
    qtbot.addWidget(composer)
    starts = []
    composer.start_requested.connect(lambda: starts.append(True))
    composer.show()

    assert composer._input.isReadOnly()
    assert not composer._input.isEnabled()
    assert composer._input.focusPolicy() == Qt.NoFocus
    assert "coming soon" in composer._input.accessibleName()
    QTest.keyClicks(composer._input, "Hello")
    QTest.keyClick(composer._input, Qt.Key_Return)
    assert composer._input.text() == ""
    for button in (composer._attachment_button, composer._dictation_button):
        assert not button.isEnabled()
        assert "coming soon" in button.accessibleName()
        button.click()
    assert starts == []

    assert composer._live_button.text() == ""
    assert composer._live_button.accessibleName() == "Start a live conversation"
    composer._live_button.setFocus(Qt.TabFocusReason)
    QTest.keyClick(composer._live_button, Qt.Key_Space)
    assert starts == [True]


def test_ending_cannot_start_or_stop_again(qtbot):
    composer = ConversationComposer()
    qtbot.addWidget(composer)
    requests = []
    composer.start_requested.connect(lambda: requests.append("start"))
    composer.stop_requested.connect(lambda: requests.append("stop"))

    composer.set_state(EngineState.STOPPING)
    composer._live_button.click()
    assert requests == []

    composer.set_state(EngineState.ERROR)
    composer._live_button.click()
    assert requests == ["start"]


def test_theme_changes_keep_mute_and_ending_resets_it_without_an_extra_command(qtbot):
    composer = ConversationComposer()
    qtbot.addWidget(composer)
    mute = []
    composer.mute_toggled.connect(mute.append)
    composer.set_state(EngineState.ACTIVE)
    composer._mute_button.click()

    for theme in ("light", "dark"):
        apply_theme(theme)
        assert composer._mute_button.isChecked()
        assert composer._mute_button.accessibleName() == "Unmute microphone"
        assert composer._live_button.text() == ""
        assert composer._live_button.accessibleName() == "End live conversation"
    assert mute == [True]

    composer.set_state(EngineState.IDLE)
    assert not composer._mute_button.isChecked()
    assert composer._mute_button.isHidden()
    assert not composer._input.isHidden()
    assert mute == [True]

    composer.set_state(EngineState.ACTIVE)
    assert composer._mute_button.accessibleName() == "Mute microphone"
