"""A newer RoomKit UI, said on the home screen: Update or Dismiss.

One line under the conversation header, only while no session is open.  The
update runs on the app's one installer (``update_check``); its outcome takes
the offer's place: Restart now, or why it failed.  The About page shares
:func:`start_update` and :func:`update_action`.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

from roomkit_ui import updates
from roomkit_ui.component_installer import UPDATE, installer, restart_app
from roomkit_ui.components import Installer
from roomkit_ui.theme_live import themed_style
from roomkit_ui.update_check import update_service

_ACTIONS = {Installer.APP: "Update", Installer.COMMAND: "Copy command", Installer.NONE: "Download"}


def update_action() -> str:
    """What the Update button says here: the app updates, or the user does."""
    return _ACTIONS[update_service().plan().how]


def start_update() -> str:
    """Update the way this install does; what to tell the user ("" while it runs).

    The app runs it where it may; otherwise the command goes on the clipboard,
    or the release page opens (a built app).
    """
    service = update_service()
    plan = service.plan()
    if plan.how is Installer.APP:
        return service.run_update()
    if plan.how is Installer.COMMAND:
        QApplication.clipboard().setText(plan.command)
        return f"{plan.note} Copied: {plan.command}".strip()
    if not QDesktopServices.openUrl(QUrl(updates.release_notes_url(service.latest))):
        return f"Download it from {updates.RELEASES_URL}"
    return plan.note


def updating() -> bool:
    runner = installer()
    return runner.busy and runner.current == UPDATE


class UpdateNotice(QWidget):
    """Offers the newer release while no session is open."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session_open = False
        self._feedback = ""  # what the last click said: a refusal, a copied command
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 16, 8)
        layout.setSpacing(8)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setAccessibleName("Update")
        themed_style(
            self._label,
            lambda c: f"font-size: 12px; color: {c['TEXT_SECONDARY']}; background: transparent;",
        )
        layout.addWidget(self._label, 1)
        self._update = self._button("Update", self._update_clicked)
        self._dismiss = self._button("Dismiss", self._dismiss_clicked)
        self._restart = self._button("Restart now", lambda: QTimer.singleShot(0, restart_app))
        for button in (self._update, self._dismiss, self._restart):
            layout.addWidget(button)
        update_service().changed.connect(self.refresh)
        runner = installer()
        runner.started.connect(self._on_started)
        runner.finished.connect(self._on_finished)
        self.refresh()

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(slot)
        return button

    def set_session_open(self, session_open: bool) -> None:
        """Hidden in a session: an update would replace the code it runs."""
        self._session_open = session_open
        self.refresh()

    def refresh(self) -> None:
        text, buttons = self._state()
        self.setVisible(bool(text) and not self._session_open)
        self._label.setText(text)
        for button in (self._update, self._dismiss, self._restart):
            button.setVisible(button in buttons)

    def _state(self) -> tuple[str, tuple[QPushButton, ...]]:
        """What the line says, and the buttons beside it."""
        version = update_service().notice
        if updating():
            return "Updating RoomKit UI…", ()
        result = installer().last_update
        if result is not None and result[0]:
            return result[1], (self._restart,)
        if not version:
            return "", ()
        if result is not None:
            return result[1], (self._update, self._dismiss)
        self._update.setText(update_action())
        text = self._feedback or f"RoomKit UI {version} is available."
        return text, (self._update, self._dismiss)

    def _update_clicked(self) -> None:
        self._feedback = start_update()
        self.refresh()

    def _dismiss_clicked(self) -> None:
        self._feedback = ""
        update_service().dismiss()

    def _on_started(self, key: str) -> None:
        if key == UPDATE:
            self.refresh()

    def _on_finished(self, key: str, _ok: bool, _message: str) -> None:
        if key == UPDATE:
            self._feedback = ""
            self.refresh()
