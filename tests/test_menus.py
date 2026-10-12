"""Shared menu styling preserves Qt editor actions, scoped QSS and live themes."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLineEdit, QMenu, QPlainTextEdit

from roomkit_ui.theme_live import apply_theme
from roomkit_ui.widgets.menus import menu_action
from roomkit_ui.widgets.settings.style import settings_colors, settings_stylesheet


@pytest.mark.parametrize("editor_type", [QLineEdit, QPlainTextEdit])
def test_qt_editor_menus_keep_actions_and_override_panel_styles(qtbot, editor_type):
    apply_theme("dark")
    panel = QDialog()
    panel.setObjectName("settingsPanel")
    panel.setStyleSheet(settings_stylesheet("dark"))
    qtbot.addWidget(panel)
    editor = editor_type("Example", panel)
    menu = editor.createStandardContextMenu()
    menu.setParent(panel, menu.windowFlags())
    actions = [(action, action.text(), action.isEnabled()) for action in menu.actions()]
    menu.ensurePolished()
    assert menu.property("roomkitMenu")
    assert menu.testAttribute(Qt.WA_TranslucentBackground)
    assert menu.windowFlags() & Qt.FramelessWindowHint
    assert actions == [(action, action.text(), action.isEnabled()) for action in menu.actions()]
    assert settings_colors("dark")["surface"] in menu.styleSheet()
    apply_theme("light")
    assert settings_colors("light")["surface"] in menu.styleSheet()
    assert actions == [(action, action.text(), action.isEnabled()) for action in menu.actions()]


def test_menu_icons_follow_theme_and_keyboard_actions_still_work(qtbot):
    apply_theme("dark")
    menu = QMenu()
    qtbot.addWidget(menu)
    action = menu_action(menu, "Choose images…", "photo")
    menu.popup(QPoint(10, 10))
    old_icon = action.icon().cacheKey()
    apply_theme("light")
    assert action.icon().cacheKey() != old_icon
    menu.setActiveAction(action)
    with qtbot.waitSignal(action.triggered):
        QTest.keyClick(menu, Qt.Key_Return)
    assert not menu.isVisible()
