"""The Live surface reflects real session events without changing voice controls."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from roomkit_ui.engine_state import EngineState
from roomkit_ui.theme_live import apply_theme
from roomkit_ui.widgets.main_window import MainWindow
from roomkit_ui.widgets.session_info import SessionInfoBar


def test_microphone_mute_preserves_playback_activity(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window._chat.clear()
    window._engine.state_changed.emit(EngineState.ACTIVE)
    assert window._header.isHidden()
    assert not window._info_bar.isHidden()
    assert not window._chat._live_empty.isHidden()

    window._engine.mic_audio_level.emit(0.8)
    window._vu._tick()
    assert window._vu._mic_display > 0
    window._controls._mute_button.click()
    window._engine.mic_audio_level.emit(0.8)
    window._vu._tick()
    assert window._vu._mic_display == 0

    # Muting the microphone never hides an answer that is still playing.
    window._engine.speaker_audio_level.emit(0.6)
    window._vu._tick()
    assert window._vu._spk_display > 0

    window._engine.state_changed.emit(EngineState.STOPPING)
    assert not window._vu._timer.isActive()
    assert not window._controls._live_button.isEnabled()
    window._engine.state_changed.emit(EngineState.IDLE)
    assert not window._header.isHidden()
    assert window._info_bar.isHidden()
    assert window._vu.isHidden()
    assert not window._vu._muted
    assert not window._chat._empty_state.isHidden()


def test_first_words_replace_the_invitation_and_survive_the_end_of_live(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window._chat.clear()
    window._engine._state = EngineState.ACTIVE
    window._engine.transcription.emit("Let's plan a walk.", "user", True, "")
    assert window._chat._live_empty.isHidden()
    assert len(window._chat._bubbles()) == 1
    window._engine.state_changed.emit(EngineState.ERROR)
    assert not window._header.isHidden()
    assert window._chat._bubbles()[0]._raw_text == "Let's plan a walk."
    window._engine._state = EngineState.IDLE
    window._history.new()
    window._engine.state_changed.emit(EngineState.ACTIVE)
    assert window._chat._bubbles() == []


def test_session_details_work_from_the_keyboard_and_survive_theme_changes(qtbot):
    bar = SessionInfoBar()
    qtbot.addWidget(bar)
    bar.set_session(
        {
            "provider": "gemini",
            "model": "a-long-model-name-that-must-stay-readable",
            "tools": [{"name": "Weather", "description": "Look up the forecast"}],
            "failed_servers": ["Calendar"],
        }
    )
    bar.resize(420, bar.sizeHint().height())
    bar.show()
    assert bar._detail_area.isHidden()
    QTest.keyClick(bar._toggle_button, Qt.Key_Space)
    assert not bar._detail_area.isHidden()
    bar.update_cost({"input_tokens": 1200, "output_tokens": 500, "cost_usd": 0.0123})
    bar.set_attitude("Warm and concise")
    for theme in ("light", "dark"):
        apply_theme(theme)
        assert bar._toggle_button.isChecked()
        assert "a-long-model-name-that-must-stay-readable" in bar._summary_label.text()
        assert "$0.0123" in bar._summary_label.text()
        assert "Warm and concise" in bar._summary_label.text()
    bar.clear_session()
    assert bar.isHidden()
    assert not bar._toggle_button.isChecked()
    bar.set_session({"provider": "openai", "model": "another-model"})
    assert bar._detail_area.isHidden()
    assert "$0.0123" not in bar._summary_label.text()
    assert "Warm and concise" not in bar._summary_label.text()


def test_new_turns_preserve_reading_position_until_the_user_returns_to_bottom(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(420, 600)
    window.show()
    window._chat.clear()
    window._engine.state_changed.emit(EngineState.ACTIVE)
    for index in range(12):
        window._chat.add_transcription(
            f"Turn {index}: " + "A longer spoken message. " * 8, "user", True
        )
    scroll = window._chat.verticalScrollBar()
    qtbot.waitUntil(lambda: scroll.maximum() > 0 and scroll.value() == scroll.maximum())
    previous_max = scroll.maximum()
    scroll.setValue(0)
    window._chat.add_transcription("One more thing. " * 12, "user", True)
    qtbot.waitUntil(lambda: scroll.maximum() > previous_max)
    assert scroll.value() == 0
    scroll.setValue(scroll.maximum())
    previous_max = scroll.maximum()
    window._chat.add_transcription("Let's keep going. " * 12, "user", True)
    qtbot.waitUntil(lambda: scroll.maximum() > previous_max and scroll.value() == scroll.maximum())
