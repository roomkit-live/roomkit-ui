"""Shared native navigation panel: presentation, focus and slide transitions."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

from roomkit_ui.icons import svg_icon
from roomkit_ui.widgets.buttons import KeyboardButton
from roomkit_ui.widgets.navigation_brand import NavigationBrand
from roomkit_ui.widgets.settings.style import settings_colors


class SlidingPanel(QWidget):
    closed = Signal()

    def __init__(self, title: str, parent: QWidget, *, from_right: bool = False) -> None:
        super().__init__(parent)
        self._surface = parent
        self._direction = 1 if from_right else -1
        self._opening = False
        self._disabled: list[QWidget] = []
        self._return_focus: QWidget | None = None
        self.setObjectName("slidingPanel")
        self.setAttribute(Qt.WA_StyledBackground)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 0, 12, 16)
        self.body.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(10, 25, 0, 21)
        header.addWidget(NavigationBrand(), 1)
        self._close = KeyboardButton()
        self._close.setObjectName("drawerClose")
        self._close.setFixedSize(34, 34)
        self._close.setIconSize(QSize(20, 20))
        self._close.setAccessibleName(f"Close {title.lower()}")
        self._close.setToolTip(f"Close {title.lower()}")
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.clicked.connect(self.dismiss)
        header.addWidget(self._close)
        self.body.addLayout(header)
        heading = QLabel(title)
        heading.setObjectName("drawerTitle")
        heading.setContentsMargins(10, 0, 10, 10)
        self.body.addWidget(heading)
        self._animation = QPropertyAnimation(self, b"pos", self)
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.finished.connect(self._animation_finished)
        shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.dismiss)
        self.hide()

    def present(self, return_focus: QWidget | None = None) -> None:
        if self._opening:
            return
        if not self.isHidden():
            self.dismiss(immediate=True)
        # One overlay at a time, including when a request arrives mid-animation.
        for sibling in self._surface.findChildren(SlidingPanel, options=Qt.FindDirectChildrenOnly):
            if sibling is not self:
                sibling.dismiss(immediate=True)
        self._return_focus = return_focus or QApplication.focusWidget()
        self._disabled.clear()
        layout = self._surface.layout()
        if layout is not None:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                widget = item.widget() if item else None
                if widget is not None and widget.isEnabled():
                    self._disabled.append(widget)
                    widget.setEnabled(False)
        self._animation.stop()
        self.resize(self._surface.size())
        self._opening = True
        self.move(self._direction * self.width(), 0)
        self.show()
        self.raise_()
        self._close.setFocus()
        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(QPoint(0, 0))
        self._animation.start()

    def dismiss(self, *, immediate: bool = False) -> None:
        if self.isHidden():
            return
        self._opening = False
        self._animation.stop()
        if immediate:
            self._animation_finished()
            return
        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(QPoint(self._direction * self.width(), 0))
        self._animation.start()

    def _animation_finished(self) -> None:
        if self._opening:
            return
        self.hide()
        for widget in self._disabled:
            if isValid(widget):
                widget.setEnabled(True)
        self._disabled.clear()
        target, self._return_focus = self._return_focus, None
        if target is not None and isValid(target) and target.isVisible() and target.isEnabled():
            target.setFocus()
        self.closed.emit()

    def resize_to_parent(self) -> None:
        self.resize(self._surface.size())
        if self._opening:
            self._animation.stop()
            self.move(0, 0)

    def _render_theme(self) -> None:
        c = settings_colors()
        self.setStyleSheet(self._styles(c))
        self._close.setIcon(svg_icon("x-mark", c["muted"], 20))

    def _styles(self, c: dict[str, str]) -> str:
        return (
            f"QWidget#slidingPanel {{ background: {c['sidebar']}; }}"
            f"QLabel {{ background: transparent; color: {c['text']}; font-size: 12px; }}"
            "QLabel#drawerTitle { font-size: 14px; font-weight: 600; }"
            f"QLabel#drawerSection {{ color: {c['muted']}; font-size: 10px; font-weight: 600; }}"
            f"QPushButton {{ border: 1px solid transparent; border-radius: 7px;"
            f" background: transparent; color: {c['muted']}; padding: 8px 10px;"
            " text-align: left; font-size: 13px; font-weight: 500; }"
            "QPushButton#drawerClose { padding: 0; }"
            f"QPushButton:hover:enabled {{ background: {c['soft']}; }}"
            f"QPushButton:pressed:enabled {{ background: {c['selected']}; }}"
            'QPushButton[keyboardFocus="true"] {'
            f" border-color: {c['accent']}; }}"
            f"QPushButton:disabled {{ color: {c['muted']}; }}"
            f"QLineEdit {{ background: {c['soft']}; color: {c['text']};"
            f" border: 1px solid {c['outline']}; border-radius: 7px;"
            f" selection-background-color: {c['accent']};"
            " padding: 8px 10px; font-size: 13px; }"
            f"QLineEdit:focus {{ border-color: {c['accent']}; }}"
            f"QFrame#drawerFooter {{ background: transparent; border: none;"
            f" border-top: 1px solid {c['border']}; }}"
            f"QScrollBar::handle:vertical {{ background: {c['border']}; }}"
        )
