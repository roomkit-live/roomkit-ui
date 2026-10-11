"""Component availability and installation, using the application's shared installer."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.component_installer import installer, restart_app
from roomkit_ui.components import Component, Installer, components, install_plan
from roomkit_ui.theme import fixed_font_family
from roomkit_ui.widgets.settings.controls import (
    AdvancedSection,
    SettingsSection,
    StatusBadge,
    label,
    navigation_link,
)
from roomkit_ui.widgets.settings.search import normalized


class _ComponentRow(QWidget):
    def __init__(self, component: Component, page: _ComponentsPage) -> None:
        super().__init__()
        self.setObjectName("settingsLibraryItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(component.title)
        self.component = component
        self._page = page
        self.installed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(label(component.title, "settingsRowTitle"), 1)
        self.status = StatusBadge()
        heading.addWidget(self.status)
        layout.addLayout(heading)
        if component.description != component.title:
            layout.addWidget(label(component.description, "settingsHint"))
        if component.note:
            layout.addWidget(label(component.note, "settingsHint"))
        self.note = label("", "settingsHint")
        layout.addWidget(self.note)
        self.action = QPushButton()
        self.action.setAutoDefault(False)
        self.action.setCursor(Qt.PointingHandCursor)
        self.action.clicked.connect(self._act)
        layout.addWidget(self.action, 0, Qt.AlignRight)
        self.refresh()

    def refresh(self) -> None:
        plan = install_plan(self.component)
        running = installer().running
        self.installed = self.component.installed()
        active = running is not None and running.extra == self.component.extra
        self.status.set_status(
            "Installing…" if active else "Installed" if self.installed else "Not installed",
            "active" if active else "success" if self.installed else "neutral",
        )
        self.action.setVisible(
            not self.installed and not active and plan.how is not Installer.NONE
        )
        self.action.setText("Install" if plan.how is Installer.APP else "Copy command")
        self.action.setAccessibleName(f"{self.action.text()} for {self.component.title}")
        self.action.setToolTip(plan.command)
        self.action.setEnabled(plan.how is not Installer.APP or running is None)
        note = ""
        if not self.installed:
            if plan.how is Installer.NONE:
                note = plan.note
            elif plan.conflicts:
                note = f"Requires a version that conflicts with {', '.join(plan.conflicts)}."
        self.note.setText(note)
        self.note.setVisible(bool(note))

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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        layout.addWidget(
            label(
                "Components enable providers and local features. "
                "They are separate from model files and API keys. Install only what you use.",
                "settingsHint",
            )
        )
        where = _where_note()
        if where:
            layout.addWidget(label(where, "settingsHint"))

        self._activity = QWidget()
        activity = QVBoxLayout(self._activity)
        activity.setContentsMargins(0, 0, 0, 0)
        activity.setSpacing(10)
        progress = QHBoxLayout()
        self._progress = label("", "settingsHint")
        self._progress.setTextFormat(Qt.PlainText)
        progress.addWidget(self._progress, 1)
        self._cancel = QPushButton("Cancel installation")
        self._cancel.setAutoDefault(False)
        self._cancel.clicked.connect(installer().cancel)
        progress.addWidget(self._cancel)
        self._restart = QPushButton("Restart now")
        self._restart.setAutoDefault(False)
        self._restart.clicked.connect(self._restart_app)
        progress.addWidget(self._restart)
        activity.addLayout(progress)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setAccessibleName("Component installation output")
        self._log.setMaximumHeight(160)
        self._log.setStyleSheet(f'font-family: "{fixed_font_family()}"; font-size: 11px;')
        self._details = AdvancedSection("Installation details", self._log)
        activity.addWidget(self._details)
        layout.addWidget(self._activity)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a component…")
        self.search.setAccessibleName("Find a component")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        self.availability = QComboBox()
        self.availability.setAccessibleName("Component installation status")
        for title, value in (
            ("All components", ""),
            ("Installed", "installed"),
            ("Not installed", "missing"),
        ):
            self.availability.addItem(title, value)
        filters.addWidget(self.availability)
        layout.addLayout(filters)
        self.summary = label("", "settingsHint")
        summary = QHBoxLayout()
        summary.addWidget(self.summary, 1)
        self.reset = navigation_link("Clear filters")
        self.reset.clicked.connect(self.clear_filters)
        summary.addWidget(self.reset)
        layout.addLayout(summary)
        self._section = SettingsSection("Available components")
        self._rows = [_ComponentRow(component, self) for component in components()]
        self.rows = {row.component.extra: row for row in self._rows}
        for row in self._rows:
            self._section.content.addWidget(row)
        layout.addWidget(self._section)
        self.empty = label("No components match these filters.", "settingsDescription")
        layout.addWidget(self.empty)
        self.search.textChanged.connect(self._filter)
        self.availability.currentIndexChanged.connect(self._filter)
        runner = installer()
        runner.started.connect(self._on_started)
        runner.output.connect(self._append_output)
        runner.finished.connect(self._on_finished)
        self.refresh()

    def clear_filters(self) -> None:
        self.search.clear()
        self.availability.setCurrentIndex(0)

    def _filter(self) -> None:
        words = normalized(self.search.text()).split()
        status = self.availability.currentData()
        visible = 0
        for row in self._rows:
            component = row.component
            text = normalized(f"{component.title} {component.description} {component.extra}")
            matches = all(word in text for word in words) and (
                not status or (status == "installed") == row.installed
            )
            row.setVisible(matches)
            visible += matches
        installed = sum(row.installed for row in self._rows)
        self.summary.setText(f"{visible} components shown · {installed} installed")
        self._section.setVisible(visible > 0)
        self.empty.setVisible(visible == 0)
        self.reset.setVisible(bool(words or status))

    def install(self, component: Component) -> None:
        """Keep the existing conflict confirmation next to the affected component."""
        plan = install_plan(component)
        if plan.conflicts:
            answer = QMessageBox.question(
                self,
                "Install anyway?",
                f"{component.title} needs another version of a library that "
                f"{', '.join(plan.conflicts)} needs too: it would stop working. Install anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        installer().install(component)

    def refresh(self) -> None:
        runner = installer()
        running = runner.running
        self._log.setPlainText("\n".join(runner.log()))
        self._cancel.setVisible(running is not None)
        self._restart.setVisible(False)
        message = f"Installing {running.title}…" if running else ""
        if not running and runner.last_result:
            extra, installed, message = runner.last_result
            component = next(c for c in components() if c.extra == extra)
            self._restart.setVisible(
                installed and (component.needs_restart or not component.installed())
            )
        self._progress.setText(message)
        self._activity.setVisible(bool(message or runner.log()))
        self._details.setVisible(bool(runner.log()))
        for row in self._rows:
            row.refresh()
        self._filter()

    def _on_started(self, _extra: str) -> None:
        self.refresh()

    def _append_output(self, text: str) -> None:
        self._log.appendPlainText(text)
        self._details.show()
        self._activity.show()

    def _on_finished(self, _extra: str, _installed: bool, _message: str) -> None:
        self.refresh()

    def _restart_app(self) -> None:
        window = self.window()
        if window is not self and hasattr(window, "accept"):
            window.accept()
        QTimer.singleShot(0, restart_app)


def _where_note() -> str:
    if getattr(sys, "frozen", False):
        return "This build carries every component it can; the others need a Python install."
    sample = install_plan(components()[0])
    if sample.how is Installer.COMMAND and sample.note:
        return f"{sample.note} “Copy command” puts it on the clipboard."
    return ""
