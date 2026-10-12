"""Shared appearance for every Qt popup, including built-in editor menus."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QProxyStyle, QWidget

from roomkit_ui.icons import svg_icon
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.widgets.settings.style import settings_colors


def _refresh(menu: QMenu) -> None:
    c = settings_colors()
    # A local QMenu rule also wins over broad QWidget rules in Settings/panels.
    menu.setStyleSheet(f"""
        QMenu {{
            background: {c["surface"]}; color: {c["text"]};
            border: 1px solid {c["border"]}; border-radius: 12px;
            padding: 6px; font-size: 13px;
        }}
        QMenu::item {{
            background: transparent; padding: 10px 16px;
            margin: 2px 0; border-radius: 7px;
        }}
        QMenu::item:selected:enabled {{
            background: {c["selected"]}; color: {c["accent"]};
        }}
        QMenu::item:disabled {{ color: {c["muted"]}; }}
        QMenu::icon {{ padding-left: 10px; }}
        QMenu::separator {{
            height: 1px; background: {c["border"]}; margin: 5px 10px;
        }}
    """)
    for action in menu.actions():
        if glyph := action.property("roomkitIcon"):
            color = c["error"] if action.property("destructive") else c["muted"]
            action.setIcon(svg_icon(glyph, color, 18))


class _MenuStyle(QProxyStyle):
    def polish(self, target):
        # QStyle only polishes widgets/palettes/the application. A Python
        # application-wide event filter also wraps partially constructed
        # WebEngine QObjects (QWebEngineUrlRequestJob), which crashes PySide.
        if isinstance(target, QMenu) and not target.property("roomkitMenu"):
            target.setProperty("roomkitMenu", True)
            # Rounded QSS alone leaves an opaque rectangle behind the corners.
            target.setWindowFlag(Qt.FramelessWindowHint, True)
            target.setAttribute(Qt.WA_TranslucentBackground)
            bind_theme(target, partial(_refresh, target))
        return super().polish(target)


def install_menu_style(app: QApplication) -> None:
    """Style Qt-created context menus too, without replacing their actions."""
    if not hasattr(app, "_roomkit_menu_style"):
        # A fresh proxy delegates to the platform style, not to the current
        # QStyleSheetStyle wrapper (which would create a style recursion).
        app._roomkit_menu_style = _MenuStyle()
        app.setStyle(app._roomkit_menu_style)


def menu_action(menu: QMenu, text: str, icon: str, *, destructive: bool = False) -> QAction:
    action = menu.addAction(text)
    action.setProperty("roomkitIcon", icon)
    action.setProperty("destructive", destructive)
    action.setIconVisibleInMenu(True)
    c = settings_colors()
    action.setIcon(svg_icon(icon, c["error"] if destructive else c["muted"], 18))
    return action


def popup_above(menu: QMenu, button: QWidget) -> None:
    """Leave a small gap above the invoking button; Qt handles screen edges."""
    menu.popup(button.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 8)))
