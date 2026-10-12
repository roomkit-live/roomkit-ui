"""The draft grows by wrapped lines as well as explicit line breaks."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from roomkit_ui.theme_live import apply_theme
from roomkit_ui.widgets.conversation_composer import ConversationComposer


def composer(qtbot):
    widget = ConversationComposer()
    qtbot.addWidget(widget)
    widget.set_text_availability("")
    widget.resize(420, 100)
    widget.show()
    qtbot.waitUntil(lambda: widget._input.viewport().width() > 100)
    return widget


def test_shift_enter_newline_and_enter_sends_multiline_draft(qtbot):
    widget = composer(qtbot)
    sent = []
    widget.send_requested.connect(sent.append)
    editor = widget._input
    QTest.keyClicks(editor, "First line")
    QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
    QTest.keyClicks(editor, "Second line")
    assert editor.toPlainText() == "First line\nSecond line"
    assert sent == []
    QTest.keyClick(editor, Qt.Key_Return)
    assert sent == ["First line\nSecond line"]


def test_typed_line_breaks_put_scrollbar_at_the_right_edge(qtbot):
    widget = composer(qtbot)
    editor = widget._input
    editor.setFocus()
    for i in range(12):
        if i:
            QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
        QTest.keyClicks(editor, "T")
    # Unlike setPlainText with newlines, Shift+Enter keeps a single Qt block.
    assert editor.document().blockCount() == 1
    bar = editor.verticalScrollBar()
    qtbot.waitUntil(bar.isVisible)
    qtbot.waitUntil(lambda: editor.geometry().bottom() < widget._live_button.y())
    bar_center = bar.mapTo(widget._surface, QPoint(bar.width() // 2, 0))
    assert bar_center.x() > widget._live_button.geometry().center().x()
    assert editor.toPlainText() == "\n".join("T" for _ in range(12))
    editor.selectAll()
    QTest.keyClicks(editor, "Short")
    qtbot.waitUntil(lambda: editor.height() == 30 and not bar.isVisible())
    qtbot.waitUntil(lambda: editor.geometry().right() < widget._dictation_button.x())


def test_eight_lines_then_scroll_and_shrink_after_send(qtbot):
    widget = composer(qtbot)
    editor = widget._input
    initial = editor.height()
    editor.setPlainText("\n".join(f"Line {i}" for i in range(8)))
    qtbot.waitUntil(lambda: editor.height() > initial)
    eight = editor.height()
    assert editor.verticalScrollBar().maximum() == 0
    editor.insertPlainText("More text\n" * 20)
    qtbot.waitUntil(lambda: editor.verticalScrollBar().maximum() > 0)
    assert editor.height() == eight
    assert editor.horizontalScrollBar().maximum() == 0
    for theme in ("dark", "light"):
        apply_theme(theme)
        assert editor.height() == eight
    widget.clear_draft()
    qtbot.waitUntil(lambda: editor.height() == initial)
    assert editor.verticalScrollBar().maximum() == 0


def test_pasted_text_wraps_and_remains_editable_beyond_eight_lines(qtbot):
    widget = composer(qtbot)
    editor = widget._input
    editor.setFocus()
    draft = "A longer paragraph which wraps naturally. " * 30
    QApplication.clipboard().setText(draft)
    editor.paste()
    qtbot.waitUntil(lambda: editor.document().lineCount() > 8)
    qtbot.waitUntil(lambda: editor.verticalScrollBar().maximum() > 0)
    assert editor.document().blockCount() == 1
    assert editor.toPlainText() == draft
    assert editor.height() <= 8 * editor.fontMetrics().lineSpacing() + 10
    editor.selectAll()
    QTest.keyClicks(editor, "Short draft")
    qtbot.waitUntil(lambda: editor.height() == 30)
    assert editor.toPlainText() == "Short draft"
