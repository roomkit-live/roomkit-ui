"""Tool rows keep results distinct, details optional, and output inert."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from roomkit_ui.theme_live import apply_theme
from roomkit_ui.tool_events import ToolCall, ToolResult
from roomkit_ui.widgets.chat_view import ChatView


def test_tool_details_are_keyboard_accessible_and_keep_literal_output(qtbot):
    chat = ChatView()
    qtbot.addWidget(chat)
    chat.resize(380, 500)
    chat.show()
    row = chat.add_tool_call(ToolCall("1", "web_search", '{"query": "Montréal"}'))
    assert chat._empty_state.isHidden()
    assert row._details is None
    QTest.keyClick(row._header, Qt.Key_Space)
    assert not row._details.isHidden()
    assert "Montréal" in row._details.toPlainText()
    assert "Waiting for the result" in row._details.toPlainText()
    chat.finish_tool_call(ToolResult("1", "completed", '<img src="file:///private/test">'))
    assert '<img src="file:///private/test">' in row._details.toPlainText()
    assert "Done" in row._header.accessibleName()
    for theme in ("dark", "light"):
        apply_theme(theme)
        assert row._header.isChecked()
        assert '<img src="file:///private/test">' in row._details.toPlainText()
    QTest.keyClick(row._header, Qt.Key_Space)
    assert row._details.isHidden()


def test_same_name_calls_keep_separate_results_and_ignore_late_updates(qtbot):
    chat = ChatView()
    qtbot.addWidget(chat)
    first = chat.add_tool_call(ToolCall("1", "search", "{}"))
    second = chat.add_tool_call(ToolCall("2", "search", "{}"))
    chat.finish_tool_call(ToolResult("2", "failed", "Unavailable"))
    assert first.result is None
    assert second.result.status == "failed"
    chat.finish_tool_call(ToolResult("1", "completed", "Found"))
    assert first.result.text == "Found"
    chat.finish_tool_call(ToolResult("2", "completed", "Duplicate"))
    assert second.result.text == "Unavailable"
    chat.clear()
    chat.finish_tool_call(ToolResult("1", "completed", "Late"))
    assert chat.tool_call("1") is None


def test_large_results_have_bounded_plain_text_preview(qtbot):
    chat = ChatView()
    qtbot.addWidget(chat)
    row = chat.add_tool_call(ToolCall("1", "read_file", "{}"))
    result = "A" * 100_000
    row.finish(ToolResult("1", "completed", result))
    row._header.click()
    assert len(row._details.toPlainText()) < 21_000
    assert "Preview limited" in row._details.toPlainText()
    assert row.result.text == result  # An interactive app still receives the full result.


def test_clearing_chat_releases_embedded_app_resources(qtbot):
    released = []

    class App(QWidget):
        def deleteLater(self):  # noqa: N802
            released.append(True)
            super().deleteLater()

    chat = ChatView()
    qtbot.addWidget(chat)
    row = chat.add_tool_call(ToolCall("1", "chart", "{}"))
    row.attach_app(App())
    chat.clear()
    assert released == [True]
