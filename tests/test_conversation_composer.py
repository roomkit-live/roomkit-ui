"""Text requires an AI configuration; Live stays available independently."""

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
    assert "Settings" in composer._input.placeholderText()
    QTest.keyClicks(composer._input, "Hello")
    QTest.keyClick(composer._input, Qt.Key_Return)
    assert composer._input.toPlainText() == ""
    for button in (composer._attachment_button, composer._dictation_button):
        assert not button.isEnabled()
        button.click()
    assert composer._attachment_button.accessibleName() == "Add images"
    assert "coming soon" in composer._dictation_button.accessibleName()
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


def test_configured_input_sends_by_enter_or_button_and_stops_generation(qtbot):
    composer = ConversationComposer()
    qtbot.addWidget(composer)
    composer.show()
    sends, stops, starts = [], [], []
    composer.send_requested.connect(sends.append)
    composer.stop_requested.connect(lambda: stops.append(True))
    composer.start_requested.connect(lambda: starts.append(True))
    composer.set_text_availability("")
    assert composer._input.isEnabled() and not composer._input.isReadOnly()
    QTest.keyClicks(composer._input, "  Bonjour  ")
    assert composer._live_button.accessibleName() == "Send message"
    QTest.keyClick(composer._input, Qt.Key_Return)
    composer._live_button.click()
    assert sends == ["Bonjour", "Bonjour"]
    # The window clears only after accepting the request.
    composer.clear_draft()
    for state in (EngineState.CONNECTING, EngineState.ACTIVE):
        composer.set_state(state, text_mode=True)
        assert not composer._input.isHidden()
        assert composer._mute_button.isHidden()
        assert composer._live_button.width() == 44
        assert composer._live_button.accessibleName() == "Stop response"
        composer._input.setPlainText("Next draft")
        QTest.keyClick(composer._input, Qt.Key_Return)
        composer._live_button.click()
    assert sends == ["Bonjour", "Bonjour"] and stops == [True, True]
    composer.set_state(EngineState.STOPPING, text_mode=True)
    composer._live_button.click()
    assert stops == [True, True]
    composer.set_state(EngineState.IDLE, text_mode=True)
    assert composer._input.toPlainText() == "Next draft"
    assert composer._live_button.accessibleName() == "Send message"
    composer.clear_draft()
    QTest.keyClick(composer._input, Qt.Key_Return)
    assert starts == []
    composer._live_button.click()
    assert starts == [True]


def test_configuration_removal_disables_without_losing_a_draft(qtbot):
    composer = ConversationComposer()
    qtbot.addWidget(composer)
    composer.set_text_availability("")
    composer._input.setPlainText("Unsent message")
    composer.set_text_availability("Add your Anthropic key in Settings…")
    sends = []
    composer.send_requested.connect(sends.append)
    composer._send()
    assert sends == [] and not composer._input.isEnabled()
    assert "Anthropic" in composer._input.toolTip()
    composer.set_text_availability("")
    assert composer._input.toPlainText() == "Unsent message"
    assert composer._live_button.accessibleName() == "Send message"


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
