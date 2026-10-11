"""Cross-platform clipboard + simulated-paste + focus helpers.

Used by both the dictation pipeline (``stt_engine``) and the voice tool
handler (``engine_tools._paste_text``).  Kept in its own module so the
OS-specific shell-outs (pbcopy / wl-copy / xclip, AppleScript /
xdotool, macOS NSWorkspace) don't muddle the STT session code.  Windows
goes through the Win32 API instead, in ``paste_windows``.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys

logger = logging.getLogger(__name__)


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


def _simulate_paste() -> bool:
    """Simulate paste keystroke into the focused window.

    Terminals typically use Ctrl+Shift+V, while other apps use Ctrl+V.
    Returns True on success, False when the keystroke was refused — the
    text is still on the clipboard then (:func:`paste_failure_message`).
    """
    if sys.platform == "darwin":
        return _paste_macos()
    if sys.platform == "win32":
        from roomkit_ui import paste_windows

        return paste_windows.send_ctrl_v()
    if _is_wayland():
        return _run_paste_command(["wtype", "-M", "ctrl", "v", "-m", "ctrl"])
    keys = "ctrl+shift+v" if _is_terminal_focused() else "ctrl+v"
    return _run_paste_command(["xdotool", "key", "--clearmodifiers", keys])


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
            exc.stderr.decode(errors="replace").strip(),
        )
        return False


def _run_paste_command(argv: list[str]) -> bool:
    try:
        subprocess.run(argv, check=True, timeout=5)
    except subprocess.CalledProcessError as exc:
        logger.warning("%s paste failed (rc=%d)", argv[0], exc.returncode)
        return False
    return True


def paste_failure_message() -> str:
    """What to tell the user when :func:`_simulate_paste` returned False."""
    if sys.platform == "darwin":
        return (
            "Accessibility permission required for auto-paste. "
            "Text copied to clipboard — paste manually with ⌘V.\n"
            "Grant access in System Settings → Privacy & Security → Accessibility."
        )
    if sys.platform == "win32":
        return (
            "Windows refused the paste keystroke — the focused window may be "
            "running as administrator. Text copied to clipboard — paste manually "
            "with Ctrl+V."
        )
    return "Auto-paste failed. Text copied to clipboard — paste manually with Ctrl+V."


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
