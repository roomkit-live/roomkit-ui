"""Windows clipboard and paste keystroke, through the Win32 API via ctypes.

Windows has no helper program to shell out to the way ``pbcopy`` or
``xclip`` serve the other platforms, and callers run these in a thread
pool, so Qt's clipboard (GUI thread only) is not an option either.

``SendInput`` is called directly rather than through pynput: pynput drops
its return value, and that value is the only sign that the keystroke was
refused — which happens when the focused window runs elevated.

Struct fields use fixed-width types so the layouts match Windows on any
platform, which keeps them testable away from Windows.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56

_OPEN_ATTEMPTS = 10
_OPEN_RETRY_SECONDS = 0.02


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint32),
        ("wParamL", ctypes.c_uint16),
        ("wParamH", ctypes.c_uint16),
    ]


class _InputUnion(ctypes.Union):
    # The mouse member is never used, but it is the largest: without it
    # sizeof(INPUT) is short and SendInput rejects every event.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _InputUnion)]


def _key_event(vk: int, *, up: bool) -> INPUT:
    event = INPUT(type=INPUT_KEYBOARD)
    event.u.ki = KEYBDINPUT(wVk=vk, dwFlags=KEYEVENTF_KEYUP if up else 0)
    return event


def ctrl_v_events() -> ctypes.Array[INPUT]:
    """Ctrl down, V down, V up, Ctrl up."""
    return (INPUT * 4)(
        _key_event(VK_CONTROL, up=False),
        _key_event(VK_V, up=False),
        _key_event(VK_V, up=True),
        _key_event(VK_CONTROL, up=True),
    )


@functools.cache
def _user32() -> Any:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (ctypes.c_uint, ctypes.c_void_p, ctypes.c_int)
    user32.SendInput.restype = ctypes.c_uint
    user32.OpenClipboard.argtypes = (ctypes.c_void_p,)
    user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
    user32.SetClipboardData.restype = ctypes.c_void_p
    return user32


@functools.cache
def _kernel32() -> Any:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
    return kernel32


def send_ctrl_v() -> bool:
    """Type Ctrl+V into the focused window. False when Windows refused it."""
    events = ctrl_v_events()
    sent = _user32().SendInput(len(events), events, ctypes.sizeof(INPUT))
    if sent != len(events):
        logger.warning(
            "SendInput inserted %d of %d events (error %d) — is the focused "
            "window running as administrator?",
            sent,
            len(events),
            ctypes.get_last_error(),
        )
        return False
    return True


def copy_text(text: str) -> None:
    """Put *text* on the clipboard as Unicode. Raises ``OSError`` on failure."""
    kernel32 = _kernel32()
    data = (text + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise ctypes.WinError(ctypes.get_last_error())
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    _hand_to_clipboard(handle)


def _hand_to_clipboard(handle: int) -> None:
    """Give *handle* to the clipboard, which owns it once accepted."""
    user32, kernel32 = _user32(), _kernel32()
    if not _open_clipboard(user32):
        kernel32.GlobalFree(handle)
        raise OSError("The clipboard is held by another application")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        user32.CloseClipboard()


def _open_clipboard(user32: Any) -> bool:
    # Another process — a clipboard manager, typically — may hold it briefly.
    for _ in range(_OPEN_ATTEMPTS):
        if user32.OpenClipboard(None):
            return True
        time.sleep(_OPEN_RETRY_SECONDS)
    return False
