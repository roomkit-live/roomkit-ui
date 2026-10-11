"""Paste: which keystroke reaches which window, and what a failure reports."""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys

import pytest

from roomkit_ui import paste, paste_windows
from roomkit_ui.engine_tools import ToolMixin

# -- X11: terminal detection -------------------------------------------------


@pytest.mark.parametrize(
    "xprop",
    [
        'WM_CLASS(STRING) = "libreoffice", "libreoffice-writer"',
        'WM_CLASS(STRING) = "code", "Code"',
        'WM_CLASS(STRING) = "Navigator", "firefox"',
        'WM_CLASS(STRING) = "steam", "Steam"',
        "WM_CLASS:  not found.",
    ],
)
def test_applications_are_not_terminals(xprop):
    """Before: "st" matched "wm_class(string)", so every app got Ctrl+Shift+V."""
    assert not paste.is_terminal_class(paste.parse_wm_class(xprop))


@pytest.mark.parametrize(
    "xprop",
    [
        'WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"',
        'WM_CLASS(STRING) = "xfce4-terminal", "Xfce4-terminal"',
        'WM_CLASS(STRING) = "qterminal", "qterminal"',
        'WM_CLASS(STRING) = "st-256color", "St"',
        'WM_CLASS(STRING) = "org.wezfurlong.wezterm", "org.wezfurlong.wezterm"',
        'WM_CLASS(STRING) = "xterm", "XTerm"',
        'WM_CLASS(STRING) = "kitty", "kitty"',
    ],
)
def test_terminals_are_recognised(xprop):
    assert paste.is_terminal_class(paste.parse_wm_class(xprop))


def test_wm_class_values_are_parsed_in_order():
    out = 'WM_CLASS(STRING) = "gnome-terminal-server", "Gnome-terminal"\n'
    assert paste.parse_wm_class(out) == ["gnome-terminal-server", "Gnome-terminal"]


class FakeRun:
    """Stands in for subprocess.run: answers xdotool/xprop, records the rest."""

    def __init__(self, wm_class: str) -> None:
        self.wm_class = wm_class
        self.keystrokes: list[list[str]] = []

    def __call__(self, argv, **_kwargs):
        if argv[:2] == ["xdotool", "getactivewindow"]:
            return subprocess.CompletedProcess(argv, 0, stdout="12345\n")
        if argv[0] == "xprop":
            return subprocess.CompletedProcess(argv, 0, stdout=self.wm_class)
        self.keystrokes.append(argv)
        return subprocess.CompletedProcess(argv, 0)


@pytest.fixture
def x11(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


def test_x11_application_gets_plain_ctrl_v(x11, monkeypatch):
    run = FakeRun('WM_CLASS(STRING) = "libreoffice", "libreoffice-writer"\n')
    monkeypatch.setattr(subprocess, "run", run)

    assert paste._simulate_paste()
    assert run.keystrokes == [["xdotool", "key", "--clearmodifiers", "ctrl+v"]]


def test_x11_terminal_gets_ctrl_shift_v(x11, monkeypatch):
    run = FakeRun('WM_CLASS(STRING) = "konsole", "konsole"\n')
    monkeypatch.setattr(subprocess, "run", run)

    assert paste._simulate_paste()
    assert run.keystrokes == [["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"]]


def test_x11_refused_keystroke_reports_failure(x11, monkeypatch):
    def run(argv, **_kwargs):
        if argv[0] == "xdotool" and argv[1] == "key":
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0, stdout="")

    monkeypatch.setattr(subprocess, "run", run)
    assert paste._simulate_paste() is False


# -- Windows -----------------------------------------------------------------


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[str] = []

    def no_subprocess(argv, **_kwargs):
        raise AssertionError(f"no helper program on Windows: {argv}")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    monkeypatch.setattr(paste_windows, "copy_text", lambda text: calls.append(f"copy:{text}"))
    monkeypatch.setattr(paste_windows, "send_ctrl_v", lambda: calls.append("ctrl+v") or True)
    return calls


def test_windows_copies_through_win32_not_xclip(windows):
    """Before: Windows fell through to xclip and always failed."""
    paste._copy_to_clipboard("bonjour")
    assert windows == ["copy:bonjour"]


def test_windows_pastes_with_ctrl_v(windows):
    assert paste._simulate_paste()
    assert windows == ["ctrl+v"]


def test_ctrl_v_events_have_the_windows_layout():
    """SendInput rejects every event when sizeof(INPUT) is off."""
    assert ctypes.sizeof(paste_windows.INPUT) == (
        40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    )
    events = paste_windows.ctrl_v_events()
    keys = [(e.u.ki.wVk, bool(e.u.ki.dwFlags & paste_windows.KEYEVENTF_KEYUP)) for e in events]
    assert keys == [(0x11, False), (0x56, False), (0x56, True), (0x11, True)]


def test_failure_message_names_the_platform_shortcut(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert "Ctrl+V" in paste.paste_failure_message()
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "⌘V" in paste.paste_failure_message()


# -- the voice tool ----------------------------------------------------------


async def test_paste_tool_reports_a_refused_keystroke(monkeypatch):
    """Before: the model was told "ok" and assured the user it had pasted."""
    monkeypatch.setattr(paste, "_copy_to_clipboard", lambda _text: None)
    monkeypatch.setattr(paste, "_simulate_paste", lambda: False)

    from roomkit import ToolFailedError

    with pytest.raises(ToolFailedError, match="clipboard"):
        await ToolMixin._paste_text("hello")


async def test_paste_tool_reports_success(monkeypatch):
    monkeypatch.setattr(paste, "_copy_to_clipboard", lambda _text: None)
    monkeypatch.setattr(paste, "_simulate_paste", lambda: True)

    result = json.loads(await ToolMixin._paste_text("hello"))

    assert result == {"status": "ok", "chars": 5}
