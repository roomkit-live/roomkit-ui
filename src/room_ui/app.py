"""QApplication bootstrap with qasync event loop."""

from __future__ import annotations

import asyncio
import logging
import sys

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from room_ui.theme import STYLESHEET
from room_ui.widgets.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("RoomKit UI")
    app.setOrganizationName("RoomKit")
    app.setStyleSheet(STYLESHEET)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        loop.run_forever()
