"""QApplication bootstrap with qasync event loop."""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import logging
import os
import signal
import sys
from pathlib import Path


def _opengl_available() -> bool:
    """Probe whether the system can create an EGL/OpenGL context.

    Tries to load libEGL and call eglGetDisplay + eglInitialize.
    Returns False if any step fails — meaning Chromium/ANGLE would crash.
    """
    try:
        egl_name = ctypes.util.find_library("EGL")
        if not egl_name:
            return False
        egl = ctypes.cdll.LoadLibrary(egl_name)
        display = egl.eglGetDisplay(ctypes.c_void_p(0))
        if display is None or display == 0:
            return False
        major, minor = ctypes.c_int(0), ctypes.c_int(0)
        ok = egl.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor))
        egl.eglTerminate(display)
        return bool(ok)
    except (OSError, AttributeError):
        return False


# ── Software rendering fallback ──────────────────────────────────────────
# When the hardware GPU driver is broken or absent, we need software GL.
# LIBGL_ALWAYS_SOFTWARE=1 forces Mesa to use llvmpipe (CPU-based OpenGL)
# for both Qt Quick and Chromium's WebGL — this keeps WebGL available for
# MCP Apps (e.g. Excalidraw) while avoiding GPU driver crashes.
# The Chromium flags tell the embedded browser to allow software WebGL,
# ignore the GPU blocklist, and disable CORS for MCP App ES-module imports
# (esm.sh rejects http://127.0.0.1 origins).  Must be set *before* PySide6.
_has_opengl = _opengl_available()

os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

# Base Chromium flags (always set).
# SECURITY NOTE: --disable-web-security disables the Same-Origin Policy for
# all QWebEngineView content.  This is required for MCP App iframes that load
# ES modules from CDNs (esm.sh rejects http://127.0.0.1 origins).  The flag
# is process-wide — it cannot be scoped to individual WebViews.  Accept the
# trade-off because MCP Apps are user-configured and trusted, and the embedded
# browser never navigates to untrusted pages.
_chromium_flags = (
    "--enable-webgl-software-rendering --ignore-gpu-blocklist --disable-vulkan"
    " --disable-web-security"
)

if not _has_opengl:
    # OpenGL is completely broken — tell Chromium to not touch the GPU at all,
    # and force Qt Quick / RHI to use CPU rendering.  Without these, ANGLE
    # attempts to create an EGL context and abort()s the whole process.
    _chromium_flags += " --disable-gpu --disable-gpu-compositing --in-process-gpu"
    os.environ.setdefault("QSG_RHI_BACKEND", "sw")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", _chromium_flags)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402
from qasync import QEventLoop  # noqa: E402

from roomkit_ui.hotkey import HotkeyListener  # noqa: E402
from roomkit_ui.settings import load_settings  # noqa: E402
from roomkit_ui.stt_engine import STTEngine  # noqa: E402
from roomkit_ui.theme import get_stylesheet  # noqa: E402
from roomkit_ui.tray import TrayService  # noqa: E402
from roomkit_ui.widgets.dictation_log import DictationLog  # noqa: E402
from roomkit_ui.widgets.main_window import MainWindow  # noqa: E402

# Log to file so we can diagnose issues when launched without a console.
if sys.platform == "darwin":
    _log_dir = os.path.join(os.path.expanduser("~"), "Library", "Logs", "RoomKit UI")
else:
    _xdg = os.environ.get(
        "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
    )
    _log_dir = os.path.join(_xdg, "roomkit-ui", "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "roomkit-ui.log")

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file, mode="w"),
    ],
    force=True,
)

# Enable verbose logging for key subsystems only when DEBUG is set.
# The MCP library logs full message bodies (including HTML resources)
# at DEBUG level, so keep it at INFO unless explicitly debugging.
if os.environ.get("DEBUG"):
    logging.getLogger("mcp").setLevel(logging.DEBUG)
    logging.getLogger("roomkit").setLevel(logging.DEBUG)
    logging.getLogger("roomkit.channels.realtime_voice").setLevel(logging.DEBUG)
else:
    logging.getLogger("roomkit.channels.realtime_voice").setLevel(logging.DEBUG)

# OpenTelemetry SDK is very chatty at INFO (batch exports, connection status,
# retries).  Keep it at WARNING so only actual problems reach the console.
logging.getLogger("opentelemetry").setLevel(logging.WARNING)


def main() -> None:
    _logger = logging.getLogger(__name__)
    if not _has_opengl:
        _logger.warning(
            "OpenGL not available — running in software rendering mode. "
            "MCP App WebViews may be limited."
        )

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

    # Pre-start the Chromium subprocess so the first QWebEngineView
    # creation later doesn't freeze the UI.  Loading about:blank on
    # a throwaway page triggers the full init path.
    def _prewarm_webengine() -> None:
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage

            page = QWebEnginePage()
            page.setHtml("")
            page.loadFinished.connect(page.deleteLater)
        except (ImportError, RuntimeError) as exc:
            _logger.warning("WebEngine prewarm skipped: %s", exc)

    QTimer.singleShot(200, _prewarm_webengine)

    # -- System-wide STT dictation --
    stt = STTEngine()
    tray = TrayService()

    # On macOS, silently check permissions and show a tray notification
    # with clear instructions if anything is missing (no system popups).
    if sys.platform == "darwin":

        def _check_macos_permissions() -> None:
            try:
                _logger = logging.getLogger(__name__)

                try:
                    import HIServices  # type: ignore[import-not-found]

                    ax = HIServices.AXIsProcessTrustedWithOptions(
                        {HIServices.kAXTrustedCheckOptionPrompt: False}
                    )
                except (ImportError, AttributeError):
                    from ApplicationServices import (  # type: ignore[import-not-found]
                        AXIsProcessTrusted,
                    )

                    ax = AXIsProcessTrusted()

                _logger.info(
                    "macOS permissions: AXTrusted=%s pid=%d exe=%s",
                    ax,
                    os.getpid(),
                    sys.executable,
                )

                if not ax:
                    tray._tray.showMessage(
                        "Permissions Required",
                        "Add RoomKit UI in System Settings\n"
                        "→ Privacy & Security → Accessibility\n"
                        "for auto-paste after dictation.",
                        QSystemTrayIcon.MessageIcon.Warning,
                        8000,
                    )
            except Exception:
                pass

        QTimer.singleShot(2000, _check_macos_permissions)

    # tray → show/raise main window
    def _show_window() -> None:
        window.showNormal()
        window.raise_()
        window.activateWindow()

    tray.show_action.triggered.connect(_show_window)

    # hotkey / menu → toggle recording
    tray.dictate_action.triggered.connect(stt.toggle_recording)

    # Dictation log window
    dictation_log = DictationLog()
    tray.log_action.triggered.connect(dictation_log.show)
    tray.log_action.triggered.connect(dictation_log.raise_)

    # session state → tray icon + notification sounds
    from roomkit_ui.sounds import (
        cleanup as sounds_cleanup,
    )
    from roomkit_ui.sounds import (
        play_dictation_start,
        play_dictation_stop,
        play_session_start,
        play_session_stop,
    )

    app.aboutToQuit.connect(sounds_cleanup)

    window.session_active_changed.connect(tray.on_session_changed)
    window.session_active_changed.connect(
        lambda active: play_session_start() if active else play_session_stop()
    )

    # engine → tray status + dictation sounds + log
    stt.recording_changed.connect(tray.on_recording_changed)
    stt.recording_changed.connect(
        lambda recording: play_dictation_start() if recording else play_dictation_stop()
    )
    stt.recording_changed.connect(dictation_log.on_recording_changed)
    stt.text_ready.connect(tray.on_text_ready)
    stt.text_ready.connect(dictation_log.on_text_ready)
    stt.error_occurred.connect(tray.on_error)
    stt.error_occurred.connect(dictation_log.on_error)

    # engine → paste into focused input
    stt.text_ready.connect(stt.paste_text)

    # Global hotkey for dictation (always created, reload picks up settings changes)
    hotkey_str = settings.get("stt_hotkey", "<ctrl>+<shift>+h")
    hotkey = HotkeyListener(hotkey=hotkey_str)
    hotkey.hotkey_pressed.connect(stt.toggle_recording)
    if settings.get("stt_enabled", True):
        hotkey.start()

    # Global hotkey for assistant session start/stop
    assistant_hotkey_str = settings.get("assistant_hotkey", "<ctrl>+<shift>+a")
    assistant_hotkey = HotkeyListener(
        hotkey=assistant_hotkey_str,
        enabled_key="assistant_hotkey_enabled",
        hotkey_key="assistant_hotkey",
    )
    assistant_hotkey.hotkey_pressed.connect(window.toggle_session)
    if settings.get("assistant_hotkey_enabled", True):
        assistant_hotkey.start()

    # Hotkey → tray notification when Accessibility permission is missing
    hotkey.permission_required.connect(tray.on_permission_required)
    assistant_hotkey.permission_required.connect(tray.on_permission_required)

    # Reload hotkeys when settings are saved
    window.settings_saved.connect(hotkey.reload)
    window.settings_saved.connect(assistant_hotkey.reload)

    # Let Ctrl+C quit cleanly instead of being swallowed by the Qt loop.
    # The Qt event loop runs in C, so Python signal handlers never fire
    # unless we periodically give the interpreter control via a timer.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    _signal_timer = QTimer()
    _signal_timer.start(200)
    _signal_timer.timeout.connect(lambda: None)

    with loop:
        loop.run_forever()
