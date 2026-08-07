"""The control-bar focus ring is a keyboard aid, not a click echo."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent

from roomkit_ui.widgets.control_bar import _CenterButton, _SideButton


def _focus_in(btn, reason):
    btn.focusInEvent(QFocusEvent(QEvent.FocusIn, reason))


def test_tab_focus_shows_the_ring(qapp):
    for btn in (_SideButton(36), _CenterButton()):
        _focus_in(btn, Qt.TabFocusReason)
        assert btn._kb_focus is True
        btn.focusOutEvent(QFocusEvent(QEvent.FocusOut, Qt.MouseFocusReason))
        assert btn._kb_focus is False
        btn.deleteLater()


def test_mouse_and_window_focus_do_not(qapp):
    for reason in (Qt.MouseFocusReason, Qt.ActiveWindowFocusReason, Qt.OtherFocusReason):
        btn = _SideButton(36)
        _focus_in(btn, reason)
        assert btn._kb_focus is False
        btn.deleteLater()
