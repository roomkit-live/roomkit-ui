"""Custom borders follow keyboard focus, not clicks or window activation."""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent

from roomkit_ui.widgets.buttons import KeyboardButton


@pytest.mark.parametrize(
    ("reason", "visible"),
    [
        (Qt.TabFocusReason, True),
        (Qt.BacktabFocusReason, True),
        (Qt.ShortcutFocusReason, True),
        (Qt.MouseFocusReason, False),
        (Qt.ActiveWindowFocusReason, False),
        (Qt.OtherFocusReason, False),
    ],
)
def test_focus_border_follows_navigation(qtbot, reason, visible):
    button = KeyboardButton()
    qtbot.addWidget(button)
    button.focusInEvent(QFocusEvent(QEvent.FocusIn, reason))
    assert button.property("keyboardFocus") is visible
    button.focusOutEvent(QFocusEvent(QEvent.FocusOut, Qt.OtherFocusReason))
    assert button.property("keyboardFocus") is False
