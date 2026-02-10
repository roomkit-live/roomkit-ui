"""QApplication bootstrap with qasync event loop."""

from __future__ import annotations

import asyncio
import logging
import sys

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from room_ui.hotkey import HotkeyListener
from room_ui.settings import load_settings
from room_ui.stt_engine import STTEngine
from room_ui.theme import STYLESHEET
from room_ui.tray import TrayService
from room_ui.widgets.dictation_log import DictationLog
from room_ui.widgets.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    force=True,
)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("RoomKit UI")
    app.setOrganizationName("RoomKit")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLESHEET)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # -- Main voice-chat window --
    window = MainWindow()
    window.show()

    # -- System-wide STT dictation --
    settings = load_settings()
    stt = STTEngine()
    tray = TrayService()

    # hotkey / menu → toggle recording
    tray.dictate_action.triggered.connect(stt.toggle_recording)

    # Dictation log window
    dictation_log = DictationLog()
    tray.log_action.triggered.connect(dictation_log.show)
    tray.log_action.triggered.connect(dictation_log.raise_)

    # engine → tray status + log
    stt.recording_changed.connect(tray.on_recording_changed)
    stt.recording_changed.connect(dictation_log.on_recording_changed)
    stt.text_ready.connect(tray.on_text_ready)
    stt.text_ready.connect(dictation_log.on_text_ready)
    stt.error_occurred.connect(tray.on_error)
    stt.error_occurred.connect(dictation_log.on_error)

    # engine → paste into focused input
    stt.text_ready.connect(stt.paste_text)

    # Global hotkey (when enabled)
    hotkey = None
    if settings.get("stt_enabled", True):
        hotkey_str = settings.get("stt_hotkey", "<ctrl>+<shift>+h")
        hotkey = HotkeyListener(hotkey=hotkey_str)
        hotkey.hotkey_pressed.connect(stt.toggle_recording)
        hotkey.start()

    with loop:
        loop.run_forever()
