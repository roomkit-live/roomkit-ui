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

    Linux only. macOS and Windows render through Metal and Direct3D (ANGLE)
    and ship no libEGL: probing there failed on every stock machine, which
    then ran with the GPU disabled and a false "OpenGL not available".
    """
    if not sys.platform.startswith("linux"):
        return True
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


def _graphics_env(has_opengl: bool) -> dict[str, str]:
    """Environment the graphics stack reads at load: set *before* PySide6.

    The Chromium flags always allow software WebGL and ignore the GPU
    blocklist. Never add --disable-web-security: it is process-wide, and
    with it an MCP App reads any cross-origin response, local and LAN
    services included (a name like 127.0.0.1.nip.io gets past a hostname
    check). The same-origin policy is what keeps that out of reach; ES-module
    imports from CDNs work without it (esm.sh answers
    `Access-Control-Allow-Origin: *`).

    Without OpenGL, Chromium must not touch the GPU at all — ANGLE would
    try an EGL context and abort() the process — and Qt Quick renders on the
    CPU (QT_QUICK_BACKEND; QSG_RHI_BACKEND has no software value). Only then
    is LIBGL_ALWAYS_SOFTWARE set: it forces Mesa onto llvmpipe, so on a
    working GPU it cost hardware rendering for nothing, and it leaks into
    every child process.
    """
    flags = "--enable-webgl-software-rendering --ignore-gpu-blocklist --disable-vulkan"
    env: dict[str, str] = {}
    if not has_opengl:
        flags += " --disable-gpu --disable-gpu-compositing --in-process-gpu"
        env["QT_QUICK_BACKEND"] = "software"
        env["LIBGL_ALWAYS_SOFTWARE"] = "1"
    env["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
    return env


_has_opengl = _opengl_available()
for _key, _value in _graphics_env(_has_opengl).items():
    os.environ.setdefault(_key, _value)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402
from qasync import QEventLoop  # noqa: E402

from roomkit_ui.hotkey import HotkeyListener  # noqa: E402
from roomkit_ui.paths import migrate_legacy_mac_data  # noqa: E402
from roomkit_ui.settings import load_settings  # noqa: E402
from roomkit_ui.stt_engine import STTEngine  # noqa: E402
from roomkit_ui.theme import get_stylesheet  # noqa: E402
from roomkit_ui.tray import TrayService  # noqa: E402
from roomkit_ui.widgets.dictation_log import DictationLog  # noqa: E402
from roomkit_ui.widgets.main_window import MainWindow  # noqa: E402
from roomkit_ui.widgets.menus import install_menu_style  # noqa: E402


def _configure_logging() -> None:
    """Log to the console and to a file, so a launch without a console can be diagnosed.

    The file starts fresh on every launch (mode="w").  That is why this runs
    from main() and not at import: ``--doctor`` imports this module too, and
    would wipe the log of the app it runs beside.
    """
    if sys.platform == "darwin":
        log_dir = os.path.join(os.path.expanduser("~"), "Library", "Logs", "RoomKit UI")
    else:
        xdg = os.environ.get(
            "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
        )
        log_dir = os.path.join(xdg, "roomkit-ui", "logs")
    os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(log_dir, "roomkit-ui.log"), mode="w"),
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
        logging.getLogger("mcp").setLevel(logging.INFO)
        logging.getLogger("roomkit").setLevel(logging.INFO)
        logging.getLogger("roomkit.channels.realtime_voice").setLevel(logging.INFO)

    # OpenTelemetry SDK is very chatty at INFO (batch exports, connection status,
    # retries).  Keep it at WARNING so only actual problems reach the console.
    logging.getLogger("opentelemetry").setLevel(logging.WARNING)


def build_wake_word(window):
    """The wake word's controller; ``apply()`` arms it from the settings."""
    from roomkit_ui.wakeword.controller import (
        WakeWordController,
        build_capture_source,
        build_listener,
    )

    return WakeWordController(
        window._engine,
        build_source=build_capture_source,
        build_listener=build_listener,
    )


def _reload_wake_word(wake) -> None:
    """Apply what was saved, then listen again now Settings has closed."""
    wake.apply(load_settings())
    wake.resume("settings")


def _create_app() -> QApplication:
    """The QApplication: identity and icon; it outlives its windows.

    Built before anything reads settings: QSettings finds the user's file
    through the organization and application names set here.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("RoomKit UI")
    app.setOrganizationName("RoomKit")
    app.setQuitOnLastWindowClosed(False)
    icon_name = "icon-macos.png" if sys.platform == "darwin" else "icon.png"
    icon_path = Path(__file__).resolve().parent / "assets" / icon_name
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def install_asyncgen_hooks(loop: asyncio.AbstractEventLoop) -> None:
    """Have the loop close the async generators a loop body leaves early.

    asyncio's run_forever installs these hooks; qasync's does not.  Without
    them, a generator abandoned with ``break`` (roomkit leaves an STT stream
    that way to drop an echo) is closed by the garbage collector, outside the
    loop: its ``finally`` cannot await, "async generator ignored GeneratorExit"
    is printed, and what it should have closed stays open — a streaming STT's
    websocket and the task feeding it audio.  With them, the loop runs its
    ``aclose()`` as a task.
    """
    firstiter = getattr(loop, "_asyncgen_firstiter_hook", None)
    finalizer = getattr(loop, "_asyncgen_finalizer_hook", None)
    if firstiter is None or finalizer is None:
        logging.getLogger(__name__).warning("Event loop has no async generator hooks")
        return
    sys.set_asyncgen_hooks(firstiter=firstiter, finalizer=finalizer)


def _prewarm_webengine() -> None:
    """Start the Chromium subprocess before the first MCP App needs it.

    Creating the first QWebEngineView otherwise freezes the UI; loading a
    blank page on a throwaway QWebEnginePage runs the full init path.
    """
    from roomkit_ui.features import unavailable_reason

    if unavailable_reason("mcp-apps") is not None:
        # Not installed: MCP Apps show as plain tool pills, nothing to warm.
        logging.getLogger(__name__).debug("WebEngine prewarm skipped: no mcp-apps extra")
        return
    try:
        from PySide6.QtWebEngineCore import QWebEnginePage

        page = QWebEnginePage()
        page.setHtml("")
        page.loadFinished.connect(page.deleteLater)
    except (ImportError, RuntimeError) as exc:
        logging.getLogger(__name__).warning("WebEngine prewarm skipped: %s", exc)


def _check_macos_permissions(tray: TrayService) -> None:
    """Say in the tray when Accessibility is missing — no system popup."""
    logger = logging.getLogger(__name__)
    try:
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

        logger.info(
            "macOS permissions: AXTrusted=%s pid=%d exe=%s", ax, os.getpid(), sys.executable
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


def _wire_tray_and_dictation(
    app: QApplication, window: MainWindow, stt: STTEngine, tray: TrayService
) -> DictationLog:
    """Connect the tray, dictation log and sounds to the window and dictation.

    Returns the dictation log window, which the caller keeps alive.
    """
    from roomkit_ui.sounds import (
        cleanup as sounds_cleanup,
    )
    from roomkit_ui.sounds import (
        play_dictation_start,
        play_dictation_stop,
        play_session_start,
        play_session_stop,
    )

    def _show_window() -> None:
        window.showNormal()
        window.raise_()
        window.activateWindow()

    tray.show_action.triggered.connect(_show_window)
    tray.dictate_action.triggered.connect(stt.toggle_recording)

    dictation_log = DictationLog()
    tray.log_action.triggered.connect(dictation_log.show)
    tray.log_action.triggered.connect(dictation_log.raise_)

    # session state → tray icon + notification sounds
    app.aboutToQuit.connect(sounds_cleanup)
    window.session_active_changed.connect(tray.on_session_changed)
    window.session_active_changed.connect(
        lambda active: play_session_start() if active else play_session_stop()
    )

    # dictation → tray status + sounds + log, then paste into the focused input
    stt.recording_changed.connect(tray.on_recording_changed)
    stt.recording_changed.connect(
        lambda recording: play_dictation_start() if recording else play_dictation_stop()
    )
    stt.recording_changed.connect(dictation_log.on_recording_changed)
    stt.text_ready.connect(tray.on_text_ready)
    stt.text_ready.connect(dictation_log.on_text_ready)
    stt.error_occurred.connect(tray.on_error)
    stt.error_occurred.connect(dictation_log.on_error)
    stt.text_ready.connect(stt.paste_text)
    return dictation_log


def _start_hotkeys(
    settings: dict, window: MainWindow, stt: STTEngine, tray: TrayService
) -> tuple[HotkeyListener, HotkeyListener]:
    """Start the dictation and assistant hotkeys; settings saves reload them."""
    hotkey = HotkeyListener(hotkey=settings.get("stt_hotkey", "<ctrl>+<shift>+h"))
    hotkey.hotkey_pressed.connect(stt.toggle_recording)

    assistant_hotkey = HotkeyListener(
        hotkey=settings.get("assistant_hotkey", "<ctrl>+<shift>+a"),
        enabled_key="assistant_hotkey_enabled",
        hotkey_key="assistant_hotkey",
    )
    assistant_hotkey.hotkey_pressed.connect(window.toggle_session)

    # Hotkey → tray notification when Accessibility permission is missing or
    # the shortcut cannot be parsed.  Connected before start(), which is
    # where both are first reported.
    for listener in (hotkey, assistant_hotkey):
        listener.permission_required.connect(tray.on_permission_required)
        listener.hotkey_invalid.connect(tray.on_hotkey_invalid)

    if settings.get("stt_enabled", True):
        hotkey.start()
    if settings.get("assistant_hotkey_enabled", True):
        assistant_hotkey.start()

    window.settings_saved.connect(hotkey.reload)
    window.settings_saved.connect(assistant_hotkey.reload)
    return hotkey, assistant_hotkey


def _wire_wake_word(
    app: QApplication, window: MainWindow, stt: STTEngine, tray: TrayService, settings: dict
):
    """Arm the wake word and keep it deaf whenever it should not listen."""
    wake = build_wake_word(window)
    # Stand down while a session or dictation holds the conversation: left
    # armed, the listener hears the assistant's own reply and wakes on it.
    window.session_active_changed.connect(
        lambda active: wake.suspend("session") if active else wake.resume("session")
    )
    stt.busy_changed.connect(
        lambda rec: wake.suspend("dictation") if rec else wake.resume("dictation")
    )
    wake.detected.connect(window.start_from_wake_word)
    wake.error.connect(tray.on_error)
    # Deaf while Settings is open: re-recording the phrase there would
    # otherwise open a session behind the dialog.
    window.settings_opened.connect(lambda: wake.suspend("settings"))
    window.settings_saved.connect(lambda: _reload_wake_word(wake))
    # Release the shared microphone on the way out, or the device stays held
    # until the process is torn down.
    app.aboutToQuit.connect(wake.close)
    wake.apply(settings)
    return wake


def _quit_on_sigint(app: QApplication) -> QTimer:
    """Let Ctrl+C quit cleanly instead of being swallowed by the Qt loop.

    The Qt event loop runs in C, so Python signal handlers never fire unless
    the interpreter periodically gets control — the returned timer does that
    and must be kept alive.
    """
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)
    return timer


def main() -> None:
    if "--doctor" in sys.argv[1:]:
        # Which optional backends this install carries, and how to complete it.
        # Runs before any Qt object exists so it works over SSH and in CI.
        from roomkit_ui.features import print_report

        print_report()
        return

    _configure_logging()
    # Before anything reads a data folder: older macOS versions kept half of
    # them under ~/.local/share.
    migrate_legacy_mac_data()
    if not _has_opengl:
        logging.getLogger(__name__).warning(
            "OpenGL not available — running in software rendering mode. "
            "MCP App WebViews may be limited."
        )

    app = _create_app()
    settings = load_settings()
    app.setStyleSheet(get_stylesheet(settings.get("theme", "dark")))
    install_menu_style(app)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    install_asyncgen_hooks(loop)

    window = MainWindow()
    window.show()
    QTimer.singleShot(200, _prewarm_webengine)

    stt = window._stt
    tray = TrayService()
    if sys.platform == "darwin":
        QTimer.singleShot(2000, lambda: _check_macos_permissions(tray))

    # Kept referenced for the app's lifetime: Qt connections alone do not.
    dictation_log = _wire_tray_and_dictation(app, window, stt, tray)  # noqa: F841
    hotkeys = _start_hotkeys(settings, window, stt, tray)  # noqa: F841
    wake = _wire_wake_word(app, window, stt, tray, settings)  # noqa: F841
    sigint_timer = _quit_on_sigint(app)  # noqa: F841

    with loop:
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(stt.shutdown())
