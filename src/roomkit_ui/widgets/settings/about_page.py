"""About page with license and credits."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from roomkit_ui.theme import colors


class _AboutPage(QWidget):
    """About page with license and credits."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        c = colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        title = QLabel("About")
        title.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        # App name + version
        app_name = QLabel("RoomKit UI")
        app_name.setStyleSheet("font-size: 24px; font-weight: 700; background: transparent;")
        layout.addWidget(app_name)

        desc = QLabel("A desktop voice assistant powered by RoomKit.")
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(desc)

        url = "https://www.roomkit.live"
        color = c["ACCENT_BLUE"]
        website = QLabel(f'<a href="{url}" style="color: {color};">www.roomkit.live</a>')
        website.setOpenExternalLinks(True)
        website.setStyleSheet("font-size: 13px; background: transparent;")
        layout.addWidget(website)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {c['SEPARATOR']};")
        layout.addWidget(sep)

        # License
        license_title = QLabel("License")
        license_title.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(license_title)

        license_text = QLabel(
            "MIT License\n\n"
            "Copyright (c) 2026 Sylvain Boily\n\n"
            "Permission is hereby granted, free of charge, to any person obtaining "
            "a copy of this software and associated documentation files, to deal in "
            "the Software without restriction, including without limitation the rights "
            "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell "
            "copies of the Software, and to permit persons to whom the Software is "
            "furnished to do so, subject to the following conditions:\n\n"
            "The above copyright notice and this permission notice shall be included "
            "in all copies or substantial portions of the Software.\n\n"
            'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS '
            "OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, "
            "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT."
        )
        license_text.setWordWrap(True)
        license_text.setStyleSheet(
            f"font-size: 12px; color: {c['TEXT_SECONDARY']};"
            f" line-height: 1.5; background: transparent;"
            f" padding: 12px; border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 8px;"
        )
        layout.addWidget(license_text)

        layout.addStretch()
