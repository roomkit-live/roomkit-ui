"""Application identity, updates, support information and the complete project license."""

from importlib.metadata import PackageNotFoundError, version
from platform import system

from PySide6.QtCore import Qt, QTimer, QUrl, qVersion
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from roomkit_ui import updates
from roomkit_ui.component_installer import UPDATE, installer, restart_app
from roomkit_ui.install_env import InstallKind
from roomkit_ui.update_check import update_service
from roomkit_ui.widgets.settings.controls import (
    AdvancedSection,
    FeedbackLabel,
    SettingsSection,
    SettingsToggle,
    label,
    navigation_link,
    page_layout,
)
from roomkit_ui.widgets.update_notice import start_update, update_action, updating


def _app_version() -> str:
    try:
        return version("roomkit-ui")
    except PackageNotFoundError:
        return "Development build"


class _AboutPage(QWidget):
    def __init__(self, settings: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        layout = page_layout(
            self, "About", "RoomKit UI brings your voice assistants together on the desktop."
        )
        identity = SettingsSection("RoomKit UI", "A desktop voice assistant powered by RoomKit.")
        self.version = label(_app_version(), "settingsRowTitle")
        identity.add_row("Version", "Installed application version", self.version)
        platform_name = {"Darwin": "macOS"}.get(system(), system())
        self.platform = label(f"{platform_name} · Qt {qVersion()}", "settingsHint")
        identity.add_row("Runtime", "System and interface toolkit", self.platform)
        layout.addWidget(identity)
        layout.addWidget(self._updates_section(settings or {}))
        self.copy_info = QPushButton("Copy version info")
        self.copy_info.setAutoDefault(False)
        self.copy_info.clicked.connect(self._copy_info)
        layout.addWidget(self.copy_info, 0, Qt.AlignLeft)
        self.feedback = FeedbackLabel()
        layout.addWidget(self.feedback)
        self.website = navigation_link("Visit roomkit.live ↗")
        self.website.clicked.connect(self._open_website)
        layout.addWidget(self.website, 0, Qt.AlignLeft)
        license_content = QWidget()
        license_layout = QVBoxLayout(license_content)
        license_layout.setContentsMargins(0, 0, 0, 0)
        license_copy = "\n\n".join(
            " ".join(part.splitlines()) for part in LICENSE_TEXT.split("\n\n")
        )
        self.license_text = label(license_copy, "settingsHint")
        self.license_text.setTextFormat(Qt.PlainText)
        self.license_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        license_layout.addWidget(self.license_text)
        self.license = AdvancedSection("MIT license · © 2026 Sylvain Boily", license_content)
        layout.addWidget(self.license)
        layout.addStretch()

    def _updates_section(self, settings: dict) -> SettingsSection:
        section = SettingsSection("Updates")
        self.update_check = SettingsToggle(
            "Check for updates automatically", bool(settings.get("update_check", True))
        )
        # A checkout moves with git: never checked, its switch kept as it is.
        self.update_check.setEnabled(update_service().kind is not InstallKind.CHECKOUT)
        section.add_row(
            "Check for updates automatically",
            "Once a day, look up the latest release on PyPI (GitHub for the built app).",
            self.update_check,
        )
        row = QWidget()
        row.setObjectName("settingsRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(18, 12, 18, 16)
        self.update_status = label("", "settingsHint")
        line.addWidget(self.update_status, 1)
        self.update_button = self._button("Update", self._update)
        self.release_notes = navigation_link("Release notes ↗")
        self.release_notes.clicked.connect(self._open_release_notes)
        self.restart_button = self._button("Restart now", self._restart)
        self.check_now = navigation_link("Check now")
        self.check_now.clicked.connect(update_service().check_now)
        for widget in (self.update_button, self.release_notes, self.restart_button):
            line.addWidget(widget)
        line.addWidget(self.check_now)
        section.content.addWidget(row)
        self._update_feedback = ""
        update_service().changed.connect(self._show_update)
        installer().started.connect(self._on_job_started)
        installer().finished.connect(self._on_job_finished)
        self._show_update()
        return section

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(slot)
        return button

    def get_settings(self) -> dict:
        return {"update_check": self.update_check.isChecked()}

    def _show_update(self) -> None:
        service = update_service()
        result = installer().last_update
        latest = service.latest
        shown: tuple[QWidget, ...] = ()
        if service.kind is InstallKind.CHECKOUT:
            text = "A source checkout: update it with git pull."
        elif updating():
            text = "Updating RoomKit UI…"
        elif result is not None and result[0]:
            text, shown = result[1], (self.restart_button,)
        elif latest:
            text = self._update_feedback or (result[1] if result else "")
            text = text or f"RoomKit UI {latest} is available."
            self.update_button.setText(update_action())
            shown = (self.update_button, self.release_notes, self.check_now)
        else:
            text, shown = self._check_status(service), (self.check_now,)
        self.update_status.setText(text)
        for widget in (
            self.update_button,
            self.release_notes,
            self.restart_button,
            self.check_now,
        ):
            widget.setVisible(widget in shown)

    @staticmethod
    def _check_status(service) -> str:
        if service.checking:
            return "Checking for updates…"
        if service.error:
            return f"Could not check for updates: {service.error}"
        return "RoomKit UI is up to date." if service.checked else ""

    def _update(self) -> None:
        self._update_feedback = start_update()
        self._show_update()

    def _open_release_notes(self) -> None:
        url = updates.release_notes_url(update_service().latest)
        if not QDesktopServices.openUrl(QUrl(url)):
            self._update_feedback = f"Could not open {url} in your browser."
            self._show_update()

    def _restart(self) -> None:
        window = self.window()
        if window is not self and hasattr(window, "accept"):
            window.accept()  # Settings saves on the way out
        QTimer.singleShot(0, restart_app)

    def _on_job_started(self, key: str) -> None:
        if key == UPDATE:
            self._show_update()

    def _on_job_finished(self, key: str, _ok: bool, _message: str) -> None:
        if key == UPDATE:
            self._update_feedback = ""
            self._show_update()

    def _copy_info(self) -> None:
        QApplication.clipboard().setText(
            f"RoomKit UI {self.version.text()}\n{self.platform.text()}"
        )
        self.feedback.set_status("Version information copied.", "success")

    def _open_website(self) -> None:
        if not QDesktopServices.openUrl(QUrl("https://www.roomkit.live")):
            self.feedback.set_status("Could not open the website in your browser.", "error")


# Kept inline so the license is available in frozen builds as well.
LICENSE_TEXT = """MIT License

Copyright (c) 2026 Sylvain Boily

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""
