"""Components tab: every optional backend, whether this install has it, and Install.

The install itself runs on the app's one installer (``component_installer``),
so it goes on when the dialog closes; reopened, the tab shows it still
running, its output so far included.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.component_installer import installer, restart_app
from roomkit_ui.components import Component, Installer, components, install_plan
from roomkit_ui.theme import colors, fixed_font_family

_INTRO = (
    "Optional parts of RoomKit UI: AI providers, local speech, dictation, MCP App "
    "views… Install the ones you use; a provider marked “not installed” in the other "
    "tabs needs its component here."
)


def _secondary(text: str, size: int = 12) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"font-size: {size}px; color: {colors()['TEXT_SECONDARY']}; background: transparent;"
    )
    return label


class _ComponentRow(QWidget):
    """One component: what it brings, whether it is here, and how to add it."""

    def __init__(self, component: Component, page: _ComponentsPage) -> None:
        super().__init__()
        self.component = component
        self._page = page
        c = colors()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        text = QVBoxLayout()
        title = QLabel(component.title)
        title.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent;")
        text.addWidget(title)
        if component.description != component.title:
            text.addWidget(_secondary(component.description))
        if component.note:
            text.addWidget(_secondary(component.note, 11))
        layout.addLayout(text, 1)

        self.status = QLabel()
        self.status.setStyleSheet(f"font-size: 12px; color: {c['TEXT_SECONDARY']};")
        layout.addWidget(self.status)
        self.action = QPushButton()
        self.action.clicked.connect(self._act)
        layout.addWidget(self.action)
        self.refresh()

    def refresh(self) -> None:
        plan = install_plan(self.component)
        running = installer().running
        installed = self.component.installed()
        if running is not None and running.extra == self.component.extra:
            self.status.setText("Installing…")
        else:
            self.status.setText("✓ Installed" if installed else "Not installed")
        self.action.setVisible(not installed and plan.how is not Installer.NONE)
        self.action.setText("Install" if plan.how is Installer.APP else "Copy command")
        self.action.setToolTip(plan.command)
        self.action.setEnabled(plan.how is not Installer.APP or running is None)

    def _act(self) -> None:
        plan = install_plan(self.component)
        if plan.how is Installer.COMMAND:
            QApplication.clipboard().setText(plan.command)
            self.action.setText("Copied")
            return
        self._page.install(self.component)


class _ComponentsPage(QWidget):
    def __init__(self, settings: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        c = colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Components")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)
        layout.addWidget(_secondary(_INTRO, 13))
        where = _where_note()
        if where:
            layout.addWidget(_secondary(where, 12))

        frame = QWidget()
        frame.setStyleSheet(
            f"background: {c['BG_SECONDARY']}; border: 1px solid {c['SEPARATOR']};"
            " border-radius: 8px;"
        )
        rows = QVBoxLayout(frame)
        rows.setContentsMargins(4, 4, 4, 4)
        rows.setSpacing(0)
        self._rows = [_ComponentRow(component, self) for component in components()]
        for row in self._rows:
            rows.addWidget(row)
        layout.addWidget(frame)

        progress = QHBoxLayout()
        self._progress = _secondary("", 13)
        progress.addWidget(self._progress, 1)
        self._cancel = QPushButton("Cancel")
        self._cancel.clicked.connect(installer().cancel)
        progress.addWidget(self._cancel)
        self._restart = QPushButton("Restart now")
        self._restart.clicked.connect(self._restart_app)
        progress.addWidget(self._restart)
        layout.addLayout(progress)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(160)
        self._log.setStyleSheet(f'font-family: "{fixed_font_family()}"; font-size: 11px;')
        layout.addWidget(self._log)
        layout.addStretch()

        runner = installer()
        runner.started.connect(self._on_started)
        runner.output.connect(self._log.appendPlainText)
        runner.finished.connect(self._on_finished)
        self._show_state()

    def install(self, component: Component) -> None:
        """Install *component*, once the user agreed to what it would break."""
        plan = install_plan(component)
        if plan.conflicts:
            answer = QMessageBox.question(
                self,
                "Install anyway?",
                f"{component.title} needs another version of a library that "
                f"{', '.join(plan.conflicts)} needs too: it would stop working. "
                "Install anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        installer().install(component)

    def _show_state(self) -> None:
        """What the installer is doing, for a tab opened at any moment."""
        running = installer().running
        self._log.setPlainText("\n".join(installer().log()))
        self._log.setVisible(bool(installer().log()))
        self._cancel.setVisible(running is not None)
        self._restart.setVisible(False)
        self._progress.setText(f"Installing {running.title}…" if running is not None else "")
        for row in self._rows:
            row.refresh()

    def _on_started(self, _extra: str) -> None:
        self._show_state()
        self._log.setVisible(True)

    def _on_finished(self, extra: str, installed: bool, message: str) -> None:
        self._show_state()
        self._progress.setText(message)
        component = next(c for c in components() if c.extra == extra)
        needs_restart = component.needs_restart or not component.installed()
        self._restart.setVisible(installed and needs_restart)

    def _restart_app(self) -> None:
        # Close the dialog first: closing it is what saves the settings.
        window = self.window()
        if window is not self and hasattr(window, "accept"):
            window.accept()
        QTimer.singleShot(0, restart_app)


def _where_note() -> str:
    """How this install takes components, said once above the list."""
    if getattr(sys, "frozen", False):
        return "This build carries every component it can; the others need a Python install."
    sample = install_plan(components()[0])
    if sample.how is Installer.COMMAND and sample.note:
        return f"{sample.note} “Copy command” puts it on the clipboard."
    return ""
