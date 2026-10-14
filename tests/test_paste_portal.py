"""Wayland paste through the RemoteDesktop portal, where GNOME refuses wtype.

A fake session bus plays the portal: each request answers on its Response
signal, as xdg-desktop-portal does.
"""

from __future__ import annotations

import contextlib
import stat
import subprocess
import sys
import threading
from collections import deque
from types import SimpleNamespace

import pytest
from jeepney import HeaderFields
from jeepney.wrappers import new_error, new_method_return

from roomkit_ui import paste, paste_portal

CTRL_V = (paste_portal.CONTROL_L, paste_portal.LETTER_V)
SESSION = "/org/freedesktop/portal/desktop/session/1_42/roomkit"


class FakePortal:
    """The session bus as the RemoteDesktop portal answers it."""

    unique_name = ":1.42"

    def __init__(self, *, portal=True, device_types=7, answer=0, new_token="token-2"):
        self.portal = portal
        self.device_types = device_types
        self.answer = answer
        self.new_token = new_token
        self.calls: list[tuple[str, tuple]] = []
        self._response: tuple[int, dict] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def send_and_get_reply(self, msg, *, timeout=None):
        member = msg.header.fields[HeaderFields.member]
        self.calls.append((member, msg.body))
        if member == "Get":
            if not self.portal:
                return new_error(msg, "org.freedesktop.DBus.Error.UnknownInterface")
            return new_method_return(msg, "v", (("u", self.device_types),))
        if member in ("CreateSession", "SelectDevices", "Start"):
            self._response = self._answer(member)
            return new_method_return(msg, "o", ("/request",))
        return new_method_return(msg)

    def _answer(self, member: str) -> tuple[int, dict]:
        if member == "CreateSession":
            return 0, {"session_handle": ("s", SESSION)}
        if member == "Start" and self.answer == 0:
            return 0, {"devices": ("u", 1), "restore_token": ("s", self.new_token)}
        return (self.answer if member == "Start" else 0), {}

    @contextlib.contextmanager
    def filter(self, _rule):
        yield deque()

    def recv_until_filtered(self, _queue, *, timeout=None):
        assert self._response is not None
        response, self._response = self._response, None
        return SimpleNamespace(body=response)

    def members(self) -> list[str]:
        return [member for member, _body in self.calls if member != "AddMatch"]

    def keys(self) -> list[tuple[int, int]]:
        return [(b[2], b[3]) for m, b in self.calls if m == "NotifyKeyboardKeysym"]

    def options(self, member: str) -> dict:
        return next(body[-1] for m, body in self.calls if m == member)


@pytest.fixture
def bus(monkeypatch, tmp_path):
    """Install a FakePortal as the session bus; the token lives in tmp_path."""
    monkeypatch.setattr(paste_portal, "data_dir", lambda: tmp_path)

    def install(**kwargs) -> FakePortal:
        fake = FakePortal(**kwargs)
        monkeypatch.setattr("jeepney.io.blocking.open_dbus_connection", lambda bus: fake)
        return fake

    return install


def test_a_paste_presses_ctrl_v_and_keeps_the_restore_token(bus):
    portal = bus()

    paste_portal.press_keys(CTRL_V)

    assert portal.members() == [
        "Get",
        "CreateSession",
        "SelectDevices",
        "Start",
        "NotifyKeyboardKeysym",
        "NotifyKeyboardKeysym",
        "NotifyKeyboardKeysym",
        "NotifyKeyboardKeysym",
        "Close",
    ]
    assert portal.keys() == [(0xFFE3, 1), (0x76, 1), (0x76, 0), (0xFFE3, 0)]
    selected = portal.options("SelectDevices")
    assert selected["types"] == ("u", 1) and selected["persist_mode"] == ("u", 2)
    assert "restore_token" not in selected  # first paste: the desktop asks
    token = paste_portal.token_path()
    assert token.read_text() == "token-2"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600


def test_the_next_paste_skips_the_question_with_the_newest_token(bus):
    paste_portal.token_path().write_text("token-1")
    paste_portal.token_path().chmod(0o644)
    portal = bus(new_token="token-2")

    paste_portal.press_keys(CTRL_V)

    assert portal.options("SelectDevices")["restore_token"] == ("s", "token-1")
    assert paste_portal.token_path().read_text() == "token-2"  # a token serves once
    assert stat.S_IMODE(paste_portal.token_path().stat().st_mode) == 0o600


def test_a_declined_permission_presses_nothing_and_closes_the_session(bus):
    portal = bus(answer=1)

    with pytest.raises(paste_portal.PortalRefusedError, match="declined"):
        paste_portal.press_keys(CTRL_V)

    assert portal.keys() == []
    assert portal.members()[-1] == "Close"
    assert not paste_portal.token_path().exists()


def test_a_caller_that_gave_up_gets_no_late_keystroke(bus):
    """A permission granted after a tool's time bound must not paste into
    whatever has the focus by then."""
    portal = bus()
    cancelled = threading.Event()
    cancelled.set()

    paste_portal.press_keys(CTRL_V, cancelled=cancelled)

    assert portal.keys() == []
    assert portal.members()[-1] == "Close"
    assert paste_portal.token_path().read_text() == "token-2"  # the yes still counts


@pytest.mark.parametrize("kwargs", [{"portal": False}, {"device_types": 2}])
def test_no_portal_keyboard_is_unavailable_before_any_session(bus, kwargs):
    portal = bus(**kwargs)

    with pytest.raises(paste_portal.PortalUnavailableError):
        paste_portal.press_keys(CTRL_V)

    assert portal.members() == ["Get"]


# -- paste.py: which Wayland path, and what a refusal says ----------------------------


@pytest.fixture
def wayland(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")


def _no_helpers(argv, **_kwargs):
    raise AssertionError(f"no helper program with the portal: {argv}")


def test_gnome_pastes_through_the_portal_not_wtype(wayland, bus, monkeypatch):
    portal = bus()
    monkeypatch.setattr(subprocess, "run", _no_helpers)

    assert paste._simulate_paste()
    assert portal.keys() == [(0xFFE3, 1), (0x76, 1), (0x76, 0), (0xFFE3, 0)]


def test_a_compositor_without_the_portal_pastes_with_wtype(wayland, bus, monkeypatch):
    bus(portal=False)
    runs: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **_kw: runs.append(argv) or subprocess.CompletedProcess(argv, 0),
    )

    assert paste._simulate_paste()
    assert runs == [["wtype", "-M", "ctrl", "v", "-m", "ctrl"]]


def test_a_refused_wtype_says_why(wayland, bus, monkeypatch):
    """Before: "Auto-paste failed", and the assistant told the user wtype was
    missing when GNOME had refused it."""
    bus(portal=False)

    def refused(argv, **_kwargs):
        stderr = b"Compositor does not support the virtual keyboard protocol\n"
        raise subprocess.CalledProcessError(1, argv, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", refused)

    with pytest.raises(paste.PasteError) as caught:
        paste._simulate_paste()

    assert str(caught.value).startswith(
        "wtype: Compositor does not support the virtual keyboard protocol. "
    )
    assert "Text copied to clipboard" in str(caught.value)


def test_a_declined_permission_reaches_the_user(wayland, bus, monkeypatch):
    bus(answer=1)
    monkeypatch.setattr(subprocess, "run", _no_helpers)

    with pytest.raises(paste.PasteError, match="permission for remote interaction"):
        paste._simulate_paste()


async def test_a_cancelled_paste_tells_the_portal_to_press_nothing(monkeypatch):
    import asyncio

    seen: list[threading.Event] = []
    started = threading.Event()
    release = threading.Event()

    def waiting(*, cancelled):
        seen.append(cancelled)
        started.set()
        release.wait(5)
        return True

    monkeypatch.setattr(paste, "_copy_to_clipboard", lambda _text: None)
    monkeypatch.setattr(paste, "_simulate_paste", waiting)

    task = asyncio.ensure_future(paste.paste_into_focused("hello"))
    await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()

    assert seen[0].is_set()
