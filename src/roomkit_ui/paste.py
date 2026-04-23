"""Cross-platform clipboard + simulated-paste + focus helpers.

Used by both the dictation pipeline (``stt_engine``) and the voice tool
handler (``engine_tools._paste_text``).  Kept in its own module so the
OS-specific shell-outs (pbcopy / wl-copy / xclip, AppleScript /
xdotool, macOS NSWorkspace) don't muddle the STT session code.
"""

from __future__ import annotations

import logging
import os
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


def _is_terminal_focused() -> bool:
    """Check if the focused X11 window is a terminal emulator."""
    try:
        # Get active window ID
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
        wm_class = result.stdout.strip().lower()
        terminal_classes = (
            "terminal",
            "konsole",
            "alacritty",
            "kitty",
            "xterm",
            "urxvt",
            "tilix",
            "terminator",
            "gnome-terminal",
            "xfce4-terminal",
            "mate-terminal",
            "sakura",
            "st",
            "wezterm",
            "foot",
            "claude",
        )
        return any(t in wm_class for t in terminal_classes)
    except Exception:
        return False


def _simulate_paste() -> bool:
    """Simulate paste keystroke into the focused window.

    Terminals typically use Ctrl+Shift+V, while other apps use Ctrl+V.
    Returns True on success, False if permission is missing.
    """
    if sys.platform == "darwin":
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
    elif _is_wayland():
        try:
            subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"], check=True, timeout=5)
        except subprocess.CalledProcessError as exc:
            logger.warning("wtype paste failed (rc=%d)", exc.returncode)
            return False
    elif _is_terminal_focused():
        try:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"],
                check=True,
                timeout=5,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning("xdotool paste failed (rc=%d)", exc.returncode)
            return False
    else:
        try:
            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], check=True, timeout=5)
        except subprocess.CalledProcessError as exc:
            logger.warning("xdotool paste failed (rc=%d)", exc.returncode)
            return False
    return True


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
