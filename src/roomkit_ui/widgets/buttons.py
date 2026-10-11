"""Native buttons with a focus border reserved for keyboard navigation."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QPushButton


class KeyboardButton(QPushButton):
    """Use the keyboardFocus property in QSS instead of a persistent :focus ring."""

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._set_keyboard_focus(
            event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
        )
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._set_keyboard_focus(False)
        super().focusOutEvent(event)

    def _set_keyboard_focus(self, focused: bool) -> None:
        if self.property("keyboardFocus") is focused:
            return
        self.setProperty("keyboardFocus", focused)
        # Let Qt own the style refresh: manually unpolishing the proxy can
        # invalidate it when the containing surface also changes its QSS.
        self.setStyleSheet(self.styleSheet())
        self.update()
