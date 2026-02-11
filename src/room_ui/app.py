"""QApplication bootstrap with qasync event loop."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from room_ui.hotkey import HotkeyListener
from room_ui.settings import load_settings
from room_ui.stt_engine import STTEngine
from room_ui.theme import get_stylesheet
from room_ui.tray import TrayService
from room_ui.widgets.dictation_log import DictationLog
from room_ui.widgets.main_window import MainWindow

# Log to file so we can diagnose issues when launched from Finder (no console).
_log_dir = os.path.join(os.path.expanduser("~"), "Library", "Logs", "RoomKit UI")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "roomkit-ui.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file, mode="w"),
    ],
    force=True,
)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("RoomKit UI")
    app.setOrganizationName("RoomKit")
    app.setQuitOnLastWindowClosed(False)
    settings = load_settings()
    app.setStyleSheet(get_stylesheet(settings.get("theme", "dark")))

    icon_path = Path(__file__).resolve().parent / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # -- Main voice-chat window --
    window = MainWindow()
    window.show()

    # On macOS, check and request event-posting permissions.
    if sys.platform == "darwin":
        try:
            from ApplicationServices import AXIsProcessTrusted
            from Quartz import CGPreflightPostEventAccess, CGRequestPostEventAccess

            logger = logging.getLogger(__name__)
            ax = AXIsProcessTrusted()
            post = CGPreflightPostEventAccess()
            logger.info(
                "macOS permissions: AXTrusted=%s PostEvent=%s pid=%d exe=%s",
                ax, post, os.getpid(), sys.executable,
            )
            if not post:
                CGRequestPostEventAccess()
        except Exception:
            pass

    # -- System-wide STT dictation --
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

    # Global hotkey (always created, reload picks up settings changes)
    hotkey_str = settings.get("stt_hotkey", "<ctrl>+<shift>+h")
    hotkey = HotkeyListener(hotkey=hotkey_str)
    hotkey.hotkey_pressed.connect(stt.toggle_recording)
    if settings.get("stt_enabled", True):
        hotkey.start()

    # Reload hotkey when settings are saved
    window.settings_saved.connect(hotkey.reload)

    # Let Ctrl+C quit cleanly instead of being swallowed by the Qt loop.
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    with loop:
        loop.run_forever()
