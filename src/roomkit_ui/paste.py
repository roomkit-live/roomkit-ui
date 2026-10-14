"""Cross-platform clipboard + simulated-paste + focus helpers.

Used by both the dictation pipeline (``stt_engine``) and the voice tool
handler (``engine_tools._paste_text``).  Kept in its own module so the
OS-specific shell-outs (pbcopy / wl-copy / xclip, AppleScript /
xdotool, macOS NSWorkspace) don't muddle the STT session code.  Windows
goes through the Win32 API instead, in ``paste_windows``; GNOME and KDE on
Wayland press the keys through the RemoteDesktop portal, in ``paste_portal``.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)


class PasteError(Exception):
    """The text could not be pasted; ``str()`` is the message for the user."""


def _is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _copy_to_clipboard(text: str) -> None:
    """Copy *text* to the system clipboard."""
    if sys.platform == "darwin":
        subprocess.run(
            ["pbcopy"],
            input=text.encode(),
            check=True,
            timeout=5,
        )
    elif sys.platform == "win32":
        from roomkit_ui import paste_windows

        paste_windows.copy_text(text)
    elif _is_wayland():
        subprocess.run(
            ["wl-copy", "--", text],
            check=True,
            timeout=5,
        )
    else:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode(),
            check=True,
            timeout=5,
        )


# WM_CLASS values (instance or class) of X11 terminals, which paste on
# Ctrl+Shift+V: Ctrl+V there sends a literal ^V.  Compared exactly — a
# substring test let "st" match nearly every application.
_TERMINAL_CLASSES = frozenset(
    {
        "alacritty",
        "claude",
        "foot",
        "kitty",
        "konsole",
        "sakura",
        "st",
        "st-256color",
        "terminator",
        "tilix",
        "urxvt",
        "wezterm",
        "xterm",
    }
)


def parse_wm_class(xprop_output: str) -> list[str]:
    """The quoted values of an ``xprop WM_CLASS`` line, in order.

    ``WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"`` gives
    both names; a window without the property gives none.
    """
    _, sep, values = xprop_output.partition("=")
    return re.findall(r'"([^"]*)"', values) if sep else []


def is_terminal_class(values: list[str]) -> bool:
    """Whether any WM_CLASS value names a terminal emulator."""
    for value in values:
        # Reverse-DNS classes keep their last part: org.wezfurlong.wezterm.
        name = value.lower().rsplit(".", 1)[-1]
        # The suffix covers the *-terminal family (gnome-, xfce4-, mate-,
        # lx-, q-, deepin-) without listing each one.
        if name in _TERMINAL_CLASSES or name.endswith("terminal"):
            return True
    return False


def _is_terminal_focused() -> bool:
    """Check if the focused X11 window is a terminal emulator."""
    try:
        wid_result = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        wid = wid_result.stdout.strip()
        if not wid:
            return False
        # Get WM_CLASS via xprop (works on all xdotool versions)
        result = subprocess.run(
            ["xprop", "-id", wid, "WM_CLASS"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return is_terminal_class(parse_wm_class(result.stdout))
    except Exception:
        return False


def _simulate_paste(*, cancelled: threading.Event | None = None) -> bool:
    """Simulate paste keystroke into the focused window.

    Terminals typically use Ctrl+Shift+V, while other apps use Ctrl+V.
    Returns True on success, False when the keystroke was refused — the
    text is still on the clipboard then (:func:`paste_failure_message`).
    A refusal whose reason is known raises :class:`PasteError` saying it.
    *cancelled*, set when the caller gave up, stops a keystroke still
    waiting for the desktop's permission.
    """
    if sys.platform == "darwin":
        return _paste_macos()
    if sys.platform == "win32":
        from roomkit_ui import paste_windows

        return paste_windows.send_ctrl_v()
    if _is_wayland():
        return _paste_wayland(cancelled)
    keys = "ctrl+shift+v" if _is_terminal_focused() else "ctrl+v"
    return _run_paste_command(["xdotool", "key", "--clearmodifiers", keys])


def _paste_wayland(cancelled: threading.Event | None) -> bool:
    """GNOME and KDE take the keystroke through the RemoteDesktop portal (GNOME
    refuses wtype: no virtual keyboard protocol); wlroots compositors (Sway,
    Hyprland) have no such portal and take wtype's."""
    from roomkit_ui import paste_portal

    try:
        paste_portal.press_keys(
            (paste_portal.CONTROL_L, paste_portal.LETTER_V), cancelled=cancelled
        )
    except paste_portal.PortalUnavailableError as exc:
        logger.debug("No remote desktop portal (%s); pasting with wtype", exc)
        return _run_paste_command(["wtype", "-M", "ctrl", "v", "-m", "ctrl"])
    except paste_portal.PortalRefusedError as exc:
        logger.warning("Remote desktop portal: %s", exc)
        raise PasteError(f"{exc} {paste_failure_message()}") from exc
    except TimeoutError as exc:
        logger.warning("The desktop's paste permission was not answered in time")
        raise PasteError(
            "The desktop's request to allow pasting (remote interaction) was not "
            f"answered in time. {paste_failure_message()}"
        ) from exc
    return True


def _paste_macos() -> bool:
    # Use AppleScript via System Events — this is more reliable than
    # CGEventPost from PyInstaller bundles, where CGEventPost silently
    # drops events even when Accessibility permission is granted.
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using command down',
            ],
            check=True,
            timeout=5,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "AppleScript paste failed (rc=%d): %s",
            exc.returncode,
            (exc.stderr or b"").decode(errors="replace").strip(),
        )
        return False


def _run_paste_command(argv: list[str]) -> bool:
    """Run a keystroke helper; its refusal raises PasteError in its own words
    (wtype: "Compositor does not support the virtual keyboard protocol")."""
    try:
        subprocess.run(argv, check=True, timeout=5, capture_output=True)
    except subprocess.CalledProcessError as exc:
        reason = _last_line(exc.stderr)
        logger.warning("%s paste failed (rc=%d): %s", argv[0], exc.returncode, reason)
        if not reason:
            return False
        raise PasteError(f"{argv[0]}: {reason}. {paste_failure_message()}") from exc
    return True


def _last_line(stderr: bytes | str | None) -> str:
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


def paste_failure_message(*, timed_out: bool = False) -> str:
    """A failed keystroke after a successful copy; never claim the text is lost."""
    prefix = "Automatic paste was not confirmed before the timeout. " if timed_out else ""
    if sys.platform == "darwin":
        return prefix + (
            "Text copied to clipboard — use ⌘V if it was not inserted.\n"
            "Check System Settings → Privacy & Security → Accessibility, and "
            "Automation → System Events, for RoomKit UI or the terminal used to launch it."
        )
    if sys.platform == "win32":
        return prefix + (
            "Windows refused the paste keystroke — the focused window may be "
            "running as administrator. Text copied to clipboard — paste manually "
            "with Ctrl+V."
        )
    return prefix + "Auto-paste failed. Text copied to clipboard — paste manually with Ctrl+V."


async def paste_into_focused(text: str) -> None:
    """Copy *text* to the clipboard and paste it into the focused input.

    The clipboard and keystroke helpers block (up to seconds), so they run
    off the event loop. Raises :class:`PasteError` when a helper program is
    missing, the clipboard refuses the text, or the keystroke is refused.
    """
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _copy_to_clipboard, text)
    except FileNotFoundError as exc:
        raise PasteError(_missing_helper_message(exc.filename)) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        # OSError also covers the Win32 clipboard refusing the text.
        logger.warning("Clipboard copy failed (%s)", type(exc).__name__)
        raise PasteError(
            "Could not copy text to the clipboard. Automatic paste was skipped."
        ) from exc

    # Copy has succeeded. A keystroke timeout is not a lost transcription, and
    # must not trigger an automatic retry: the target may have pasted already.
    cancelled = threading.Event()
    try:
        pasted = await loop.run_in_executor(
            None, functools.partial(_simulate_paste, cancelled=cancelled)
        )
    except asyncio.CancelledError:
        # The caller gave up (a tool's time bound): a permission granted later
        # must not paste into whatever has the focus by then.
        cancelled.set()
        raise
    except subprocess.TimeoutExpired as exc:
        logger.warning("Automatic paste was not confirmed within %s seconds", exc.timeout)
        raise PasteError(paste_failure_message(timed_out=True)) from exc
    except FileNotFoundError as exc:
        raise PasteError(
            _missing_helper_message(exc.filename) + " " + paste_failure_message()
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Automatic paste failed (%s)", type(exc).__name__)
        raise PasteError(paste_failure_message()) from exc
    if not pasted:
        raise PasteError(paste_failure_message())


# The package each Linux helper program comes in: wl-copy is not one.
_HELPER_PACKAGES = {
    "wl-copy": "wl-clipboard",
    "wtype": "wtype",
    "xclip": "xclip",
    "xdotool": "xdotool",
}


def _missing_helper_message(program: str | None) -> str:
    message = f"Missing helper program: {program}."
    if sys.platform.startswith("linux"):
        package = _HELPER_PACKAGES.get(program or "")
        message += (
            f" Install the {package} package."
            if package
            else " Install xclip and xdotool (X11), or wl-clipboard and wtype (Wayland)."
        )
    return message


def _get_frontmost_bundle() -> str | None:
    """Return the bundle ID of the frontmost app (macOS only).

    Returns None if the frontmost app is our own process, since restoring
    focus to ourselves would cause the paste to go to the wrong window.
    """
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSWorkspace

        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front and front.processIdentifier() != os.getpid():
            return front.bundleIdentifier()  # type: ignore[no-any-return]
        return None
    except Exception:
        return None


def _activate_bundle(bundle_id: str) -> None:
    """Bring an app to the front by bundle ID (macOS only)."""
    if sys.platform != "darwin" or not bundle_id:
        return
    try:
        from AppKit import NSRunningApplication

        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
        if apps:
            # 3 = NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps
            apps[0].activateWithOptions_(3)
            logger.info("Activated app: %s", bundle_id)
    except Exception:
        logger.exception("Failed to activate app: %s", bundle_id)
