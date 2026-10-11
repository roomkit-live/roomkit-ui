"""Application identity, support information and the complete project license."""

from importlib.metadata import PackageNotFoundError, version
from platform import system

from PySide6.QtCore import Qt, QUrl, qVersion
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from roomkit_ui.widgets.settings.controls import (
    AdvancedSection,
    FeedbackLabel,
    SettingsSection,
    label,
    navigation_link,
    page_layout,
)


def _app_version() -> str:
    try:
        return version("roomkit-ui")
    except PackageNotFoundError:
        return "Development build"


class _AboutPage(QWidget):
    def __init__(self, parent=None) -> None:
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
