"""Live palette bindings tied to the lifetime of their Qt widgets."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget

from roomkit_ui.theme import colors, get_stylesheet


class _ThemeEvents(QObject):
    changed = Signal()


def theme_events() -> _ThemeEvents:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Live themes require a QApplication")
    events = getattr(app, "_roomkit_theme_events", None)
    if events is None:
        events = _ThemeEvents(app)
        app._roomkit_theme_events = events
    return events


class _ThemeBinding(QObject):
    def __init__(self, owner: QWidget, render: Callable[[], None]) -> None:
        super().__init__(owner)
        self.render = render
        theme_events().changed.connect(self.refresh)

    @Slot()
    def refresh(self) -> None:
        self.render()


def bind_theme(owner: QWidget, render: Callable[[], None], *, name: str = "theme") -> None:
    """Replace a widget's binding, never accumulate callbacks on state changes.

    Qt disconnects the receiver when its owner is destroyed, including widgets
    removed during downloads and other asynchronous work.
    """
    attribute = f"_roomkit_{name}_binding"
    binding = getattr(owner, attribute, None)
    if binding is None:
        binding = _ThemeBinding(owner, render)
        setattr(owner, attribute, binding)
    else:
        binding.render = render
    binding.refresh()


def themed_style(widget: QWidget, stylesheet: Callable[[dict[str, str]], str]) -> None:
    bind_theme(widget, lambda: widget.setStyleSheet(stylesheet(colors())), name="style")


def apply_theme(theme: str) -> None:
    """Persist and apply only the appearance preference, leaving other edits pending."""
    from roomkit_ui.settings import save_settings
    from roomkit_ui.widgets.menus import install_menu_style

    save_settings({"theme": theme})
    app = QApplication.instance()
    if isinstance(app, QApplication):
        install_menu_style(app)
        app.setStyleSheet(get_stylesheet(theme))
        theme_events().changed.emit()
        for widget in app.allWidgets():
            widget.update()
