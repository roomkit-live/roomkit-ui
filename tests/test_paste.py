"""Paste: which keystroke reaches which window, and what a failure reports."""

from __future__ import annotations

import asyncio
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


# -- macOS: copy succeeded, but System Events did not confirm the keystroke ----


@pytest.mark.parametrize("failure", ["timeout", "refused", "empty_stderr"])
async def test_macos_paste_failure_keeps_the_copy_and_explains_permissions(monkeypatch, failure):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv[0])
        if argv[0] == "pbcopy":
            assert kwargs["input"] == "Bonjour à tous".encode()
            return subprocess.CompletedProcess(argv, 0)
        assert argv[0] == "osascript"
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        stderr = None if failure == "empty_stderr" else b"Not authorized (-1743)"
        raise subprocess.CalledProcessError(1, argv, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(paste.PasteError) as caught:
        await paste.paste_into_focused("Bonjour à tous")
    message = str(caught.value)
    assert "Text copied to clipboard" in message
    assert "⌘V" in message
    assert "Accessibility" in message and "Automation → System Events" in message
    assert "terminal" in message
    assert ("timeout" in message) == (failure == "timeout")
    assert "osascript" not in message
    assert calls == ["pbcopy", "osascript"]  # Never retry a possibly delivered keystroke.


async def test_macos_success_copies_once_then_pastes_once(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv[0])
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    await paste.paste_into_focused("hello")
    assert calls == ["pbcopy", "osascript"]


@pytest.mark.parametrize("failure", ["timeout", "refused"])
async def test_a_failed_copy_never_claims_clipboard_success_or_attempts_paste(
    monkeypatch, failure
):
    def copy(text):
        # Some helpers carry the content in argv; never expose it in the error/log.
        argv = ["wl-copy", "--", text]
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 5)
        raise subprocess.CalledProcessError(1, argv)

    def forbidden():
        raise AssertionError("Must not paste the clipboard's previous content")

    monkeypatch.setattr(paste, "_copy_to_clipboard", copy)
    monkeypatch.setattr(paste, "_simulate_paste", forbidden)
    with pytest.raises(paste.PasteError, match="Could not copy") as caught:
        await paste.paste_into_focused("private transcription")
    assert "Text copied" not in str(caught.value)
    assert "private transcription" not in str(caught.value)


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


# -- one paste path for dictation and the tool ---------------------------------


async def test_a_missing_helper_names_what_to_install_on_linux(monkeypatch):
    def missing(_text):
        raise FileNotFoundError(2, "No such file", "xclip")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(paste, "_copy_to_clipboard", missing)

    with pytest.raises(paste.PasteError, match="xclip.*Install xclip"):
        await paste.paste_into_focused("hello")


async def test_dictation_reports_a_refused_paste(qapp, monkeypatch):
    from roomkit_ui.stt_engine import STTEngine

    monkeypatch.setattr(paste, "_copy_to_clipboard", lambda _text: None)
    monkeypatch.setattr(paste, "_simulate_paste", lambda: False)
    engine = STTEngine()
    errors: list[str] = []
    engine.error_occurred.connect(errors.append)

    engine.paste_text("hello")
    for _ in range(10):
        await asyncio.sleep(0.01)

    assert errors == [paste.paste_failure_message()]
