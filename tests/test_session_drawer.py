"""The session panel follows live data without taking over the conversation."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from roomkit_ui.engine_state import EngineState
from roomkit_ui.theme_live import apply_theme
from roomkit_ui.widgets.main_window import MainWindow


@pytest.fixture
def live_window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window, before_close_func=lambda w: w._engine._set_state(EngineState.IDLE))
    window.resize(420, 600)
    window.show()
    window._engine._state = EngineState.ACTIVE
    window._engine.state_changed.emit(EngineState.ACTIVE)
    window._engine.session_info.emit(
        {
            "provider": "gemini",
            "model": "a-long-model-name-that-must-stay-readable",
            "mode": "realtime",
            "models": [
                {
                    "role": "Live audio",
                    "provider": "gemini",
                    "model": "a-long-model-name-that-must-stay-readable",
                    "description": "Voice · Aoede",
                }
            ],
            "tools": [{"name": "check_weather", "description": "Look up the forecast"}],
            "skills": [{"name": "Travel", "description": "Plan a weekend away"}],
            "failed_servers": ["Calendar"],
        }
    )
    yield window
    window._engine._state = EngineState.IDLE
    window._engine.state_changed.emit(EngineState.IDLE)


def _open(window, qtbot):
    QTest.keyClick(window._info_bar._details_button, Qt.Key_Space)
    drawer = window._session_drawer
    qtbot.waitUntil(lambda: drawer.pos().x() == 0)
    assert not drawer.isHidden()
    return drawer


def test_keyboard_panel_preserves_chat_geometry_and_live_updates(live_window, qtbot):
    window = live_window
    qtbot.wait(10)
    before = window._conversation_stack.geometry()
    drawer = _open(window, qtbot)
    assert drawer.size() == window._surface.size()
    assert window._conversation_stack.geometry() == before
    assert not window._controls.isEnabled()
    assert not hasattr(window._info_bar, "_detail_area")
    assert drawer._mode.text() == "Realtime"
    assert "Gemini · a-long-model" in drawer.findChild(QLabel, "sessionModelName").text()
    assert window._info_bar.findChildren(QLabel) == []
    assert "Calendar" in drawer._unavailable.text()
    row = drawer._groups[0][1][0]
    QTest.keyClick(row.toggle, Qt.Key_Space)
    assert not row.description.isHidden()
    window._engine.session_cost.emit(
        {"input_tokens": 1200, "output_tokens": 500, "cost_usd": 0.0123}
    )
    window._engine.attitude_changed.emit("Warm and concise")
    window._engine.transcription.emit("We are still talking", "user", True, "")
    for theme in ("light", "dark"):
        apply_theme(theme)
        assert not drawer.isHidden()
        assert row.toggle.isChecked()
        assert "$0.0123" in drawer._usage.text()
        assert "Warm and concise" in drawer._attitude.text()
    assert window._engine.state == EngineState.ACTIVE
    assert window._chat._bubbles()[-1]._raw_text == "We are still talking"
    QTest.keyClick(drawer._close, Qt.Key_Escape)
    qtbot.waitUntil(drawer.isHidden)
    assert window._controls.isEnabled()
    assert window._info_bar._details_button.hasFocus()


def test_search_descriptions_refresh_and_long_lists_remain_readable(live_window, qtbot):
    window = live_window
    drawer = _open(window, qtbot)
    info = {
        "provider": "llamacpp",
        "model": "local-model",
        "tools": [
            {"name": f"lookup_{i}", "description": f"Find <saved> notes for topic {i}"}
            for i in range(35)
        ],
    }
    window._engine.session_info.emit(info)
    qtbot.waitUntil(lambda: drawer._scroll.verticalScrollBar().maximum() > 0)
    assert drawer._scroll.horizontalScrollBar().maximum() == 0
    # Native QPushButton size hints must not clip the custom name/arrow layout.
    for _, entries in drawer._groups:
        for entry in entries:
            label = entry.toggle.findChild(QLabel, "sessionEntryTitle")
            assert entry.toggle.rect().contains(label.geometry())
            assert label.height() >= label.fontMetrics().height()
    assert drawer._unavailable.isHidden()
    drawer._search.setText("topic 34")
    rows = drawer._groups[0][1]
    assert sum(not row.isHidden() for row in rows) == 1
    row = rows[-1]
    row.toggle.click()
    assert row.description.textFormat() == Qt.PlainText
    assert "<saved>" in row.description.text()
    window._engine.session_cost.emit({"input_tokens": 900, "output_tokens": 50})
    window._engine.attitude_changed.emit("Concise")
    window._engine.session_info.emit(info)
    assert not drawer.isHidden()
    assert drawer._search.text() == "topic 34"
    assert drawer._groups[0][1][-1].toggle.isChecked()
    assert drawer._usage.text() == "950 tok"
    assert "Concise" in drawer._attitude.text()
    drawer._search.setText("no such tool")
    assert not drawer._empty.isHidden()
    assert drawer._groups[0][0].isHidden()
    drawer._search.clear()
    assert all(not row.isHidden() for row in drawer._groups[0][1])


def test_hangup_clears_panel_and_late_events_cannot_restore_old_session(live_window, qtbot):
    window = live_window
    drawer = _open(window, qtbot)
    window._engine.session_cost.emit({"cost_usd": 1.5})
    window._engine.attitude_changed.emit("Warm")
    drawer._search.setText("Weather")
    window._engine._state = EngineState.IDLE
    window._engine.state_changed.emit(EngineState.IDLE)
    assert drawer.isHidden()
    assert window._controls.isEnabled()
    assert window._header._history.hasFocus()
    window._engine.session_info.emit({"provider": "old", "model": "old"})
    window._engine.session_cost.emit({"cost_usd": 99})
    window._engine.attitude_changed.emit("Old personality")
    assert not drawer._groups
    assert not drawer._search.text()
    assert not drawer._attitude.text()
    assert "99" not in drawer._usage.text()
    assert drawer._models.count() == 0
    window._engine._state = EngineState.ACTIVE
    window._engine.state_changed.emit(EngineState.ACTIVE)
    window._engine.session_info.emit({"provider": "openai", "model": "new-model"})
    _open(window, qtbot)
    assert drawer._mode.text() == "Realtime"
    assert not drawer._groups
    assert "$1.50" not in drawer._usage.text()
    assert drawer._attitude.isHidden()


def test_panels_replace_each_other_resize_and_restore_focus(live_window, qtbot):
    window = live_window
    drawer = _open(window, qtbot)
    window._history.show()
    history = window._history.drawer
    qtbot.waitUntil(lambda: history.pos().x() == 0)
    assert drawer.isHidden()
    assert not window._controls.isEnabled()
    window._show_session_details()
    qtbot.waitUntil(lambda: drawer.pos().x() == 0)
    assert history.isHidden()
    window.resize(420, 820)
    assert drawer.size() == window._surface.size()
    assert drawer.pos().x() == 0
    # Reopening during the closing animation must not lose the disabled widgets.
    drawer.dismiss()
    drawer.present(window._info_bar._details_button)
    qtbot.waitUntil(lambda: drawer.pos().x() == 0)
    drawer._back.click()
    qtbot.waitUntil(drawer.isHidden)
    assert window._controls.isEnabled()
    assert window._info_bar._details_button.hasFocus()


def test_complete_pipeline_wraps_on_a_narrow_panel_and_search_keeps_tools_reachable(
    live_window, qtbot
):
    window = live_window
    window.resize(360, 600)
    roles = [
        "Listen · STT",
        "Reason · LLM",
        "Speak · TTS",
        "Speaking decision",
        "Think while listening",
    ]
    models = [
        {
            "role": role,
            "provider": "gemini",
            "model": "a-very-long-model-name-" * 4,
            "description": "Voice · Aoede" if "TTS" in role else "",
        }
        for role in roles
    ]
    window._engine.session_info.emit(
        {
            "mode": "voice_channel",
            "models": models,
            "tools": [{"name": "check_weather", "description": "Look up the forecast"}],
        }
    )
    drawer = _open(window, qtbot)
    assert drawer._mode.text() == "Voice Channel"
    for theme in ("dark", "light"):
        apply_theme(theme)
        qtbot.wait(10)
        assert drawer._scroll.horizontalScrollBar().maximum() == 0
        assert drawer._models.count() == len(roles)
        for i, role in enumerate(roles):
            row = drawer._models.itemAt(i).widget()
            assert row.findChild(QLabel, "drawerSection").text() == role
            label = row.findChild(QLabel, "sessionModelName")
            assert row.rect().contains(label.geometry())
            assert label.textFormat() == Qt.PlainText
            assert label.height() >= label.heightForWidth(label.width())
    drawer._search.setText("forecast")
    assert drawer._overview.isHidden()
    assert not drawer._groups[0][0].isHidden()
    drawer._search.clear()
    assert not drawer._overview.isHidden()
